"""
Прогон всех тестов одной задачи с базовой изоляцией.
"""

from __future__ import annotations

import json
import logging
import platform
import subprocess
import sys

from config import settings

log = logging.getLogger("session")
crash = logging.getLogger("crash")

# Список модулей, которые РАЗРЕШЕНО импортировать участнику (через пробел)
ALLOWED_IMPORTS_STR = (
    "math statistics decimal fractions itertools functools "
    "collections datetime random re json string copy "
    "enum operator typing dataclasses heapq bisect "
    "array numbers time"
)

# ---------- шаблоны раннеров ----------

# Общий код для изоляции импортов (теперь передаем строку)
_SAFE_IMPORT_CODE = """
import builtins

ALLOWED = "__ALLOWED__".split()

_original_import = builtins.__import__

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root_module = name.split('.')[0]
    if root_module not in ALLOWED:
        raise ImportError(f"Импорт модуля '{root_module}' запрещен правилами олимпиады.")
    return _original_import(name, globals, locals, fromlist, level)

builtins.__import__ = _safe_import
"""

_SEQ_RUNNER_TEMPLATE = r'''
import json, sys, io, contextlib, traceback

__SAFE_IMPORT__

MAX_OUTPUT = __MAX_OUTPUT__

def main():
    raw = sys.stdin.read()
    payload = json.loads(raw)
    code = payload["code"]
    tests = payload["tests"]
    results = []

    for t in tests:
        buf = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(t["input"])
        try:
            with contextlib.redirect_stdout(buf):
                exec(compile(code, "<solution>", "exec"), {"__name__": "__main__"})
            out = buf.getvalue()
            if len(out) > MAX_OUTPUT:
                results.append({"id": t["id"], "out": out[:MAX_OUTPUT],
                                "rc": 1, "err": "OUTPUT_LIMIT"})
            else:
                results.append({"id": t["id"], "out": out, "rc": 0, "err": ""})
        except SystemExit as e:
            results.append({"id": t["id"], "out": buf.getvalue(),
                            "rc": 1, "err": f"SystemExit({e.code!r})"})
        except ImportError as e:
            results.append({"id": t["id"], "out": buf.getvalue(),
                            "rc": 1, "err": f"SecurityError: {e}"})
        except Exception:
            results.append({"id": t["id"], "out": buf.getvalue(),
                            "rc": 1, "err": traceback.format_exc()})
        finally:
            sys.stdin = old_stdin

    sys.stdout.write(json.dumps(results))

if __name__ == "__main__":
    main()
'''

_ISO_RUNNER_TEMPLATE = r'''
import json, sys, io, contextlib, traceback, multiprocessing as mp

__SAFE_IMPORT__

MAX_OUTPUT = __MAX_OUTPUT__
MAX_FORKS = __MAX_FORKS__

def _run(payload):
    code, stdin_data = payload
    buf = io.StringIO()
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_data)
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<solution>", "exec"), {"__name__": "__main__"})
        out = buf.getvalue()
        if len(out) > MAX_OUTPUT:
            return {"out": out[:MAX_OUTPUT], "rc": 1, "err": "OUTPUT_LIMIT"}
        return {"out": out, "rc": 0, "err": ""}
    except SystemExit as e:
        return {"out": buf.getvalue(), "rc": 1,
                "err": f"SystemExit({e.code!r})"}
    except ImportError as e:
        return {"out": buf.getvalue(), "rc": 1,
                "err": f"SecurityError: {e}"}
    except Exception:
        return {"out": buf.getvalue(), "rc": 1, "err": traceback.format_exc()}
    finally:
        sys.stdin = old_stdin

def main():
    raw = sys.stdin.read()
    payload = json.loads(raw)
    code = payload["code"]
    tests = payload["tests"]
    n = max(1, min(MAX_FORKS, len(tests)))

    try:
        with mp.Pool(processes=n) as pool:
            results = pool.map(_run, [(code, t["input"]) for t in tests])
    except Exception:
        results = [_run((code, t["input"])) for t in tests]

    for t, r in zip(tests, results):
        r["id"] = t["id"]
    sys.stdout.write(json.dumps(results))

if __name__ == "__main__":
    main()
'''

# Формируем безопасный импорт (передаем строку)
_safe_import_str = _SAFE_IMPORT_CODE.replace(
    "__ALLOWED__", ALLOWED_IMPORTS_STR
)

# Собираем финальные строки раннеров
_SEQ_RUNNER = (
    _SEQ_RUNNER_TEMPLATE
    .replace("__SAFE_IMPORT__", _safe_import_str)
    .replace("__MAX_OUTPUT__", str(settings.max_output_bytes))
)

_ISO_RUNNER = (
    _ISO_RUNNER_TEMPLATE
    .replace("__SAFE_IMPORT__", _safe_import_str)
    .replace("__MAX_OUTPUT__", str(settings.max_output_bytes))
    .replace("__MAX_FORKS__", str(settings.batch_max_forks))
)

# ---------- вспомогательные ----------

def _safe_stub(tests: list[dict], err: str) -> list[dict]:
    return [{"id": t["id"], "out": "", "rc": -1, "err": err} for t in tests]

def _apply_limits(memory_mb: int):
    if platform.system() == "Windows":
        return None

    def _limits():
        try:
            import resource
            limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ImportError, ValueError, OSError):
            pass

    return _limits

# ---------- основной API ----------

def run_batch(
    code: str,
    tests: list[dict],
    timeout_per_test: float | None = None,
    memory_mb: int | None = None,
    isolated: bool | None = None,
) -> list[dict]:
    if not tests:
        return []

    timeout_per_test = (
        timeout_per_test if timeout_per_test is not None
        else settings.default_time_limit_sec
    )
    memory_mb = (
        memory_mb if memory_mb is not None
        else settings.default_memory_limit_mb
    )
    isolated = settings.batch_isolated if isolated is None else isolated

    if isolated and platform.system() == "Windows":
        log.warning(
            "isolated=True не поддерживается на Windows, "
            "откат на последовательный прогон"
        )
        isolated = False

    payload = json.dumps({
        "code": code,
        "tests": [{"id": t["id"], "input": t["input"]} for t in tests],
    })

    runner = _ISO_RUNNER if isolated else _SEQ_RUNNER
    total_timeout = (
        timeout_per_test * len(tests) + settings.batch_extra_timeout_sec
    )
    preexec = _apply_limits(memory_mb)

    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", runner],
            input=payload,
            capture_output=True,
            text=True,
            timeout=total_timeout,
            preexec_fn=preexec,
        )
    except subprocess.TimeoutExpired:
        crash.warning("BATCH TIMEOUT (%.1fs) на %d тестов", total_timeout, len(tests))
        return _safe_stub(tests, "TIMEOUT")
    except MemoryError:
        crash.warning("BATCH MEMORY_LIMIT (%d МБ)", memory_mb)
        return _safe_stub(tests, "MEMORY_LIMIT")
    except OSError as e:
        crash.error("BATCH: не удалось запустить процесс: %s", e)
        return _safe_stub(tests, "RUNNER_ERROR")

    if proc.returncode != 0:
        crash.warning("BATCH: раннер упал rc=%d: %s", proc.returncode, (proc.stderr or "")[:300])
        return _safe_stub(tests, "RUNNER_ERROR")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        crash.error("BATCH: некорректный JSON: %r", (proc.stdout or "")[:200])
        return _safe_stub(tests, "RUNNER_ERROR")

    if not isinstance(data, list):
        return _safe_stub(tests, "RUNNER_ERROR")

    by_id = {x.get("id"): x for x in data if isinstance(x, dict)}

    result: list[dict] = []
    for t in tests:
        r = by_id.get(t["id"])
        if r is None:
            result.append({"id": t["id"], "out": "", "rc": -1, "err": "MISSING"})
            continue
        result.append({
            "id": t["id"],
            "out": r.get("out", "") or "",
            "rc": int(r.get("rc", -1)),
            "err": r.get("err", "") or "",
        })
    return result