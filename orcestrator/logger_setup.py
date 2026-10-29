"""
Настройка логирования.

Два логгера:
- "session" — все взаимодействия и выводы, пишется в logs/session.log (+ stdout);
- "crash"   — только прерванные сессии: краши, тайм-ауты, ошибки чтения,
              пишется в logs/crash.log (+ stderr).

Работа в пуле процессов:
- файловые хендлеры висят ТОЛЬКО на QueueListener (в родителе);
- и родитель, и дочерние процессы пишут в файл через QueueHandler;
- консольный StreamHandler — только у родителя (напрямую, не через очередь),
  чтобы не дублировать вывод из форков.
"""

from __future__ import annotations

import logging
import logging.handlers
import multiprocessing as mp
from pathlib import Path

from config import settings


# ---------- глобальное состояние ----------
_log_queue: "mp.Queue | None" = None
_listener: logging.handlers.QueueListener | None = None
_session_logger: logging.Logger | None = None
_crash_logger: logging.Logger | None = None


# ---------- helpers ----------
def _level(name: str, default: int) -> int:
    """Строка уровня ('INFO', 'WARNING', ...) → int. Неизвестное → default."""
    return getattr(logging, name.upper(), default)


def _make_file_handler(path: Path, level: int) -> logging.Handler:
    # Храним логи 1 день (when='D', interval=1, backupCount=1)
    h = logging.handlers.TimedRotatingFileHandler(
        path,
        when="D",
        interval=1,
        backupCount=1,  # Оставляем только сегодняшний лог (и вчерашний)
        encoding="utf-8",
    )
    h.setLevel(level)
    h.setFormatter(logging.Formatter(
        "%(asctime)s [%(processName)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    return h


def _make_console_handler(level: int, prefix: str = "") -> logging.Handler:
    h = logging.StreamHandler()
    h.setLevel(level)
    h.setFormatter(logging.Formatter(f"{prefix}%(message)s"))
    return h


# ---------- публичный API ----------
def setup_logging(logs_dir: Path | None = None) -> tuple[logging.Logger, logging.Logger]:
    """
    Создаёт и настраивает логгеры "session" и "crash".
    Повторный вызов возвращает уже созданные.
    """
    global _log_queue, _listener, _session_logger, _crash_logger

    if _session_logger is not None and _crash_logger is not None:
        return _session_logger, _crash_logger

    logs_dir = logs_dir or settings.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Очередь для логов из дочерних процессов (в пуле)
    _log_queue = mp.Queue(-1)

    # ---------- файловые хендлеры (только у listener) ----------
    session_file = _make_file_handler(
        logs_dir / settings.session_log_name, logging.DEBUG
    )
    crash_file = _make_file_handler(
        logs_dir / settings.crash_log_name, logging.DEBUG
    )

    # ---------- session ----------
    session = logging.getLogger("session")
    session.setLevel(logging.DEBUG)
    session.propagate = False

    session_qh = logging.handlers.QueueHandler(_log_queue)
    session_qh.setLevel(logging.DEBUG)
    session.addHandler(session_qh)

    session_console = _make_console_handler(
        _level(settings.session_console_level, logging.DEBUG)
    )
    session.addHandler(session_console)

    # ---------- crash ----------
    crash = logging.getLogger("crash")
    crash.setLevel(logging.DEBUG)
    crash.propagate = False

    crash_qh = logging.handlers.QueueHandler(_log_queue)
    crash_qh.setLevel(logging.DEBUG)
    crash.addHandler(crash_qh)

    crash_console = _make_console_handler(
        _level(settings.crash_console_level, logging.WARNING),
        prefix="[CRASH] ",
    )
    crash.addHandler(crash_console)

    # ---------- QueueListener ----------
    # Забирает записи из очереди и пишет в файлы.
    # Все записи в файл — через один поток, гонок за RotatingFileHandler нет.
    _listener = logging.handlers.QueueListener(
        _log_queue, session_file, crash_file,
        respect_handler_level=True,
    )
    _listener.start()

    _session_logger, _crash_logger = session, crash
    return session, crash


def get_session_logger() -> logging.Logger:
    if _session_logger is None:
        setup_logging()
    return _session_logger  # type: ignore[return-value]


def get_crash_logger() -> logging.Logger:
    if _crash_logger is None:
        setup_logging()
    return _crash_logger  # type: ignore[return-value]


def get_log_queue() -> "mp.Queue | None":
    """Возвращает очередь логов (для передачи в init_worker_logging)."""
    return _log_queue


def init_worker_logging(queue=None) -> None:
    """
    Вызывается в каждом дочернем процессе пула (initializer).

    :param queue: очередь логов из родителя. На Linux (fork) можно не
                  передавать — глобальное состояние скопируется.
                  На Windows (spawn) — обязательна, иначе _log_queue=None
                  и логи из форков потеряются.
    """
    global _log_queue
    if queue is not None:
        _log_queue = queue
    if _log_queue is None:
        return

    qh = logging.handlers.QueueHandler(_log_queue)

    for name in ("session", "crash"):
        lg = logging.getLogger(name)
        lg.handlers = [qh]
        lg.propagate = False
        lg.setLevel(logging.DEBUG)


def shutdown_logging() -> None:
    """Останавливает QueueListener. Вызывать в конце main()."""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None