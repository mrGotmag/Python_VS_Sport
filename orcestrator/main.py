import argparse
import sys
from pathlib import Path

from logger_setup import (
    setup_logging,
    init_worker_logging,
    get_session_logger,
    get_log_queue,
    shutdown_logging,
)
from pool import check_many
from reporter import print_report, print_summary, save_report_json
from config import settings


def find_task_dirs(root: Path, only_id: str | None = None) -> list[Path]:
    if not root.exists():
        return []
    dirs = sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name.isdigit()),
        key=lambda p: int(p.name),
    )
    if only_id:
        dirs = [p for p in dirs if p.name == only_id]
    return dirs


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Проверка решений олимпиадных задач.",
    )
    ap.add_argument(
        "root",
        nargs="?",
        default=str(settings.tasks_dir),
        help="папка с задачами (по умолчанию из .env)",
    )
    ap.add_argument(
        "--only",
        default=None,
        help="проверить только задачу с этим id",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=None,
        help="число воркеров (по умолчанию из .env)",
    )
    ap.add_argument(
        "--max-load",
        type=float,
        default=None,
        help="ждать, пока load average не упадёт ниже этого значения",
    )
    return ap.parse_args()


def wait_for_load(max_load: float) -> None:
    """Простой троттлинг: ждём, пока load average не упадёт."""
    import os
    import time

    while True:
        try:
            load = os.getloadavg()[0]
        except OSError:
            return  # Windows / нет getloadavg
        if load < max_load:
            return
        time.sleep(2)


def main() -> int:
    args = parse_args()
    setup_logging()
    log = get_session_logger()

    try:
        root = Path(args.root)
        task_dirs = find_task_dirs(root, args.only)

        if not task_dirs:
            log.error("Не найдено задач в %s", root)
            return 2

        workers = args.workers or settings.default_workers

        if args.max_load:
            log.info("Ожидание load < %.1f ...", args.max_load)
            wait_for_load(args.max_load)

        log.info("Старт: %d задач, %d воркеров", len(task_dirs), workers)

        reports = check_many(
            task_dirs,
            workers=workers,
            initializer=init_worker_logging,
            initargs=(get_log_queue(),),
        )

        for r in reports:
            print_report(r)
        print_summary(reports)
        save_report_json(reports, settings.report_json)
        return 0
    finally:
        shutdown_logging()


if __name__ == "__main__":
    sys.exit(main())