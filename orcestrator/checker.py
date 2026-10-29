"""
Проверка одной задачи из папки tasks/<id>/.

Ожидаемая структура папки задачи:
    task.txt      — условие (не читается чекером, только для участника)
    tests.json    — тесты
    solution.py   — решение участника (может отсутствовать → 0 баллов)

Возвращает отчёт:
{
    "id": str,
    "title": str | None,
    "status": "ok" | "partial" | "no_solution" | "no_tests" | "error",
    "score": int,
    "total": int,
    "tests": [...],
    "error": str | None
}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from code_reader import read_code, CodeReadError
from batch_runner import run_batch
from config import settings

SOLUTION_NAME = settings.solution_name
TESTS_NAME = settings.tests_name
TASK_NAME = settings.task_name

log = logging.getLogger("session")
crash = logging.getLogger("crash")


def _empty_report(task_id: str) -> dict:
    return {
        "id": task_id,
        "title": None,
        "status": "ok",
        "score": 0,
        "total": 0,
        "tests": [],
        "error": None,
    }


def _skipped_tests(tests: list[dict]) -> list[dict]:
    return [
        {"id": t["id"], "status": "skipped", "points": 0, "max_points": t["points"]}
        for t in tests
    ]


def _normalize(s) -> str:
    """Приводит к строке и (опционально) срезает хвостовые пробелы/\\n."""
    if not isinstance(s, str):
        s = "" if s is None else str(s)
    return s.rstrip() if settings.check_strip_trailing else s


def _read_tests_file(tests_path: Path, task_id: str, report: dict) -> dict | None:
    """
    Читает и парсит tests.json.
    При ошибке заполняет report и возвращает None.
    """
    if not tests_path.exists():
        report["status"] = "no_tests"
        report["error"] = f"Нет файла {TESTS_NAME}"
        crash.error("Задача %s: %s", task_id, report["error"])
        return None

    try:
        raw = tests_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        report["status"] = "no_tests"
        report["error"] = f"{TESTS_NAME} не в UTF-8: {e.reason}"
        crash.error("Задача %s: %s", task_id, report["error"])
        return None
    except OSError as e:
        report["status"] = "no_tests"
        report["error"] = f"Не удалось прочитать {TESTS_NAME}: {e}"
        crash.error("Задача %s: %s", task_id, report["error"])
        return None

    if not raw.strip():
        report["status"] = "no_tests"
        report["error"] = f"{TESTS_NAME} пустой"
        crash.error("Задача %s: %s", task_id, report["error"])
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        report["status"] = "no_tests"
        report["error"] = f"Некорректный JSON в {TESTS_NAME}: {e}"
        crash.error("Задача %s: %s", task_id, report["error"])
        return None

    if not isinstance(data, dict):
        report["status"] = "no_tests"
        report["error"] = f"{TESTS_NAME}: ожидался объект верхнего уровня"
        crash.error("Задача %s: %s", task_id, report["error"])
        return None

    tests = data.get("tests")
    if not isinstance(tests, list) or not tests:
        report["status"] = "no_tests"
        report["error"] = f"{TESTS_NAME}: список 'tests' пуст или отсутствует"
        crash.error("Задача %s: %s", task_id, report["error"])
        return None

    required = {"id", "input", "expected_output", "points"}
    for i, t in enumerate(tests, 1):
        if not isinstance(t, dict):
            report["status"] = "no_tests"
            report["error"] = f"{TESTS_NAME}: тест #{i} — не объект"
            crash.error("Задача %s: %s", task_id, report["error"])
            return None

        missing = required - t.keys()
        if missing:
            report["status"] = "no_tests"
            report["error"] = (
                f"{TESTS_NAME}: тест #{i} — нет полей {sorted(missing)}"
            )
            crash.error("Задача %s: %s", task_id, report["error"])
            return None

        if not isinstance(t["id"], (int, str)):
            report["status"] = "no_tests"
            report["error"] = f"{TESTS_NAME}: тест #{i} — 'id' должен быть int или str"
            crash.error("Задача %s: %s", task_id, report["error"])
            return None
        if not isinstance(t["input"], str):
            report["status"] = "no_tests"
            report["error"] = (
                f"{TESTS_NAME}: тест #{i} — 'input' должен быть строкой"
            )
            crash.error("Задача %s: %s", task_id, report["error"])
            return None
        if not isinstance(t["expected_output"], str):
            report["status"] = "no_tests"
            report["error"] = (
                f"{TESTS_NAME}: тест #{i} — 'expected_output' должен быть строкой"
            )
            crash.error("Задача %s: %s", task_id, report["error"])
            return None
        if not isinstance(t["points"], int) or isinstance(t["points"], bool) \
                or t["points"] <= 0:
            report["status"] = "no_tests"
            report["error"] = (
                f"{TESTS_NAME}: тест #{i} — 'points' должен быть целым > 0"
            )
            crash.error("Задача %s: %s", task_id, report["error"])
            return None

    return data


def check_task(task_dir: Path) -> dict:
    """
    Проверяет одну задачу. Возвращает отчёт.
    Никогда не бросает исключений — все ошибки попадают в report["error"].
    """
    task_id = task_dir.name
    report = _empty_report(task_id)

    log.info("--- Задача %s: начало проверки (%s)", task_id, task_dir)

    # ---------- 1) tests.json ----------
    tests_path = task_dir / TESTS_NAME
    data = _read_tests_file(tests_path, task_id, report)
    if data is None:
        return report

    meta = data.get("task", {}) or {}
    if not isinstance(meta, dict):
        meta = {}
    tests = data["tests"]

    report["title"] = str(meta.get("title", f"Задача {task_id}"))

    try:
        report["total"] = sum(int(t["points"]) for t in tests)
    except (TypeError, ValueError):
        report["status"] = "no_tests"
        report["error"] = f"{TESTS_NAME}: 'points' должен быть целым числом"
        crash.error("Задача %s: %s", task_id, report["error"])
        return report

    try:
        time_limit = float(
            meta.get("time_limit_sec", settings.default_time_limit_sec)
        )
    except (TypeError, ValueError):
        time_limit = settings.default_time_limit_sec
    try:
        memory_mb = int(
            meta.get("memory_limit_mb", settings.default_memory_limit_mb)
        )
    except (TypeError, ValueError):
        memory_mb = settings.default_memory_limit_mb

    log.info("Задача %s: %d тестов, максимум %d баллов, лимиты: %.1fs / %d МБ",
             task_id, len(tests), report["total"], time_limit, memory_mb)

    # ---------- 2) solution.py ----------
    sol_path = task_dir / SOLUTION_NAME
    if not sol_path.exists():
        report["status"] = "no_solution"
        report["error"] = f"Нет файла {SOLUTION_NAME}"
        crash.error("Задача %s: %s", task_id, report["error"])
        report["tests"] = _skipped_tests(tests)
        return report

    try:
        code = read_code(sol_path)
    except CodeReadError as e:
        report["status"] = "no_solution"
        report["error"] = str(e)
        crash.error("Задача %s: %s", task_id, report["error"])
        report["tests"] = _skipped_tests(tests)
        return report

    log.debug("Задача %s: код решения — %d символов, %d строк",
              task_id, len(code), len(code.splitlines()))

    # ---------- 3) прогон всех тестов батчем ----------
    try:
        results = run_batch(
            code,
            tests,
            timeout_per_test=time_limit,
            memory_mb=memory_mb,
            isolated=True,
        )
    except Exception as e:
        # run_batch сам ловит инфраструктурные ошибки. Если сюда долетело —
        # это баг в batch_runner, а не «нет решения». Отдельный статус.
        crash.exception("Задача %s: баг batch_runner: %s", task_id, e)
        report["status"] = "error"
        report["error"] = f"Ошибка раннера: {e}"
        report["tests"] = _skipped_tests(tests)
        return report

    # ---------- 4) разбор результатов ----------
    score = 0
    # ---------- 4) разбор результатов ----------
    total_score = 0
    total_time_ms = 0.0
    max_memory_mb = 0.0

    for t, r in zip(tests, results):
        rc = r.get("rc", -1)
        err_text = r.get("err", "") or ""
        time_ms = r.get("time_ms", 0.0)
        mem_mb = r.get("memory_mb", 0.0)

        if rc != 0:
            reason = err_text if err_text in ("TIMEOUT", "MEMORY_LIMIT", "RUNNER_ERROR", "MISSING") else \
                err_text.strip().splitlines()[-1][:200]
            log.info("Задача %s: тест #%s FAIL (%s)", task_id, t["id"], reason)
            report["tests"].append({
                "id": t["id"], "status": "fail", "reason": reason,
                "points": 0, "max_points": t["points"],
                "time_ms": time_ms, "memory_mb": mem_mb
            })
            continue

        # Если тест пройден, начисляем баллы
        out = r.get("out", "")
        if _normalize(out) == _normalize(t["expected_output"]):
            points = int(t["points"])
            total_score += points
            total_time_ms += time_ms
            max_memory_mb = max(max_memory_mb, mem_mb)

            log.info("Задача %s: тест #%s OK (+%d)", task_id, t["id"], points)

            report["tests"].append({
                "id": t["id"], "status": "ok",
                "points": points, "max_points": t["points"],
                "time_ms": time_ms, "memory_mb": mem_mb
            })
        else:
            log.info("Задача %s: тест #%s FAIL (wrong output)", task_id, t["id"])
            report["tests"].append({
                "id": t["id"], "status": "fail", "reason": "wrong output",
                "expected": t["expected_output"], "got": out,
                "points": 0, "max_points": t["points"],
                "time_ms": time_ms, "memory_mb": mem_mb
            })

    # Итоговые результаты
    report["score"] = total_score
    report["time_ms"] = total_time_ms
    report["memory_mb"] = max_memory_mb
    report["status"] = "ok" if total_score == report["total"] else "partial"

    log.info("Задача %s: итог %d/%d (%s)",
             task_id, total_score, report["total"], report["status"])
    return report