"""
Все настройки читаются из .env один раз при импорте.

Использование:
    from config import settings
    settings.tasks_dir
    settings.default_time_limit_sec
"""

from __future__ import annotations
from pydantic_settings import BaseSettings

import multiprocessing as mp
from pathlib import Path

from dotenv import load_dotenv
import os


# Загружаем .env из корня проекта (рядом с main.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _get_str(key: str, default: str) -> str:
    v = os.getenv(key)
    return v if v not in (None, "") else default


def _get_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except ValueError as e:
        raise ValueError(f".env: {key} должно быть целым, получено {v!r}") from e


def _get_float(key: str, default: float) -> float:
    v = os.getenv(key)
    if v in (None, ""):
        return default
    try:
        return float(v)
    except ValueError as e:
        raise ValueError(f".env: {key} должно быть числом, получено {v!r}") from e


def _get_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v in (None, ""):
        return default
    v = v.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError(f".env: {key} должно быть bool, получено {v!r}")


def _get_path(key: str, default: str) -> Path:
    return Path(_get_str(key, default))


class Settings(BaseSettings):
    app_name: str = "Python vs Спорт"
    secret_key: str = "super-secret-key-change-me"
    access_token_expire_minutes: int = 480  # 8 часов

    class Config:
        env_file = ".env"
    # ---------- пути ----------
    tasks_dir: Path = _get_path("TASKS_DIR", "tasks")
    logs_dir: Path = _get_path("LOGS_DIR", "logs")
    report_json: Path = _get_path("REPORT_JSON", "logs/report.json")

    solution_name: str = _get_str("SOLUTION_NAME", "solution.py")
    tests_name: str = _get_str("TESTS_NAME", "tests.json")
    task_name: str = _get_str("TASK_NAME", "task.txt")

    # ---------- логи ----------
    session_log_name: str = _get_str("SESSION_LOG_NAME", "session.log")
    crash_log_name: str = _get_str("CRASH_LOG_NAME", "crash.log")
    log_max_bytes: int = _get_int("LOG_MAX_BYTES", 10 * 1024 * 1024)
    log_backup_count: int = _get_int("LOG_BACKUP_COUNT", 5)
    session_console_level: str = _get_str("SESSION_CONSOLE_LEVEL", "INFO").upper()
    crash_console_level: str = _get_str("CRASH_CONSOLE_LEVEL", "WARNING").upper()

    # ---------- чтение кода ----------
    max_code_size_bytes: int = _get_int("MAX_CODE_SIZE_BYTES", 1_000_000)

    # ---------- запуск ----------
    default_time_limit_sec: float = _get_float("DEFAULT_TIME_LIMIT_SEC", 2.0)
    default_memory_limit_mb: int = _get_int("DEFAULT_MEMORY_LIMIT_MB", 256)
    batch_isolated: bool = _get_bool("BATCH_ISOLATED", True)
    batch_max_forks: int = _get_int("BATCH_MAX_FORKS", 4)
    batch_extra_timeout_sec: float = _get_float("BATCH_EXTRA_TIMEOUT_SEC", 5.0)
    max_output_bytes: int = _get_int("MAX_OUTPUT_BYTES", 1_000_000)

    # ---------- проверка ----------
    check_strip_trailing: bool = _get_bool("CHECK_STRIP_TRAILING", True)

    # ---------- пул ----------
    max_workers: int = _get_int("MAX_WORKERS", 8)

    @property
    def default_workers(self) -> int:
        raw = os.getenv("DEFAULT_WORKERS", "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError as e:
                raise ValueError(
                    f".env: DEFAULT_WORKERS должно быть целым, получено {raw!r}"
                ) from e
        return max(1, min(mp.cpu_count(), self.max_workers))


settings = Settings()