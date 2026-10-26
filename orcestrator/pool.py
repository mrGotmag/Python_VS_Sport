"""
Пул воркеров для проверки задач.

Ограничивает число одновременных процессов (max_workers).
"""

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from config import settings

log = logging.getLogger("session")
crash = logging.getLogger("crash")


def default_workers() -> int:
    return settings.default_workers


def check_many(
    task_dirs: list[Path],
    workers: int | None = None,
    initializer=None,
    initargs: tuple = (),
) -> list[dict]:
    """
    Проверяет задачи параллельно. Возвращает список отчётов в порядке id.

    :param initializer: функция, вызываемая в каждом воркере при старте
                        (например, init_worker_logging)
    :param initargs:    аргументы для initializer
    """
    if not task_dirs:
        return []

    workers = workers or settings.default_workers
    log.info("Параллельная проверка: %d задач, %d воркеров",
             len(task_dirs), workers)

    reports: list[dict] = []

    # check_task импортируем здесь, чтобы не тянуть logging в форк раньше времени
    from checker import check_task

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=initializer,
        initargs=initargs,
    ) as ex:
        futures = {ex.submit(check_task, d): d for d in task_dirs}
        for fut in as_completed(futures):
            d = futures[fut]
            try:
                reports.append(fut.result())
            except Exception as e:
                crash.exception("Задача %s: непредвиденная ошибка: %s", d.name, e)
                reports.append({
                    "id": d.name,
                    "title": f"Задача {d.name}",
                    "status": "error",
                    "score": 0,
                    "total": 0,
                    "tests": [],
                    "error": f"Непредвиденная ошибка: {e}",
                })

    reports.sort(key=lambda r: int(r["id"]))
    return reports