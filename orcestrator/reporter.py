"""
Печать отчёта по задачам в консоль и в session.log.
"""

import json
import logging
from pathlib import Path

from config import settings

log = logging.getLogger("session")


def print_report(r: dict) -> None:
    log.info("")
    log.info("=== Задача %s: %s ===", r["id"], r["title"])

    if r["status"] == "no_tests":
        log.warning("[SKIP] %s — 0/%d баллов", r["error"], r["total"])
        return

    if r["status"] == "no_solution":
        log.warning("[ZERO] %s — 0/%d баллов", r["error"], r["total"])
        for t in r["tests"]:
            log.info("       #%s: пропущен (0/%d)",
                     t["id"], t["max_points"])
        return

    if r["status"] == "error":
        log.error("[ERROR] %s — 0/%d баллов", r["error"], r["total"])
        for t in r["tests"]:
            log.info("       #%s: пропущен (0/%d)",
                     t["id"], t["max_points"])
        return

    for t in r["tests"]:
        if t["status"] == "ok":
            log.info("[ OK ] #%s (+%d)", t["id"], t["points"])
        else:
            reason = t.get("reason", "fail")
            extra = ""
            if "expected" in t:
                extra = f" expected {t['expected']!r}, got {t['got']!r}"
            log.info("[FAIL] #%s: %s%s", t["id"], reason, extra)

    log.info("Результат: %d/%d", r["score"], r["total"])


def print_summary(reports: list[dict]) -> None:
    grand_score = sum(r["score"] for r in reports)
    grand_total = sum(r["total"] for r in reports)
    solved = sum(1 for r in reports if r["status"] == "ok")
    no_sol = sum(1 for r in reports if r["status"] == "no_solution")
    no_tests = sum(1 for r in reports if r["status"] == "no_tests")
    errored = sum(1 for r in reports if r["status"] == "error")

    log.info("")
    log.info("ИТОГО: %d/%d баллов", grand_score, grand_total)
    log.info("Задач решено полностью: %d/%d", solved, len(reports))
    if no_sol:
        log.info("Задач без решения (0 баллов): %d", no_sol)
    if no_tests:
        log.info("Задач без тестов (пропущено): %d", no_tests)
    if errored:
        log.warning("Задач с ошибкой раннера: %d", errored)


def save_report_json(reports, path: Path | None = None):
    path = path or settings.report_json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reports, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    log.info("Отчёт сохранён в %s", path)