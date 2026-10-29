"""
Прогон всех тестов одной задачи с базовой изоляцией.
"""

from __future__ import annotations

import json
import logging
import platform
import subprocess
import sys
import threading
import time
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

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

    # --- Замер памяти: поток-монитор параллельно с процессом ---
    peak_memory_mb = 0.0
    proc = None
    stop_event = threading.Event()

    def _monitor_memory(pid: int, holder: dict, stop_evt: threading.Event) -> None:
        if not HAS_PSUTIL:
            return
        try:
            p = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        peak = 0.0
        while not stop_evt.is_set():
            try:
                mem_info = p.memory_info()
                if hasattr(mem_info, "peak_wset"):  # Windows
                    mem_val = mem_info.peak_wset / (1024 * 1024)
                else:  # Linux/macOS
                    mem_val = mem_info.rss / (1024 * 1024)
                if mem_val > peak:
                    peak = mem_val
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            if not p.is_running():
                break
            time.sleep(0.005)
        holder["peak_mb"] = peak

    mem_holder = {"peak_mb": 0.0}
    monitor = None

    # --- Запуск процесса и замер общего времени ---
    start_time = time.perf_counter()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", runner],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=preexec,
        )

        if HAS_PSUTIL:
            monitor = threading.Thread(
                target=_monitor_memory,
                args=(proc.pid, mem_holder, stop_event),
                daemon=True,
            )
            monitor.start()

        try:
            stdout, stderr = proc.communicate(input=payload, timeout=total_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            crash.warning("BATCH TIMEOUT (%.1fs) на %d тестов", total_timeout, len(tests))
            return _safe_stub(tests, "TIMEOUT")
    except MemoryError:
        crash.warning("BATCH MEMORY_LIMIT (%d МБ)", memory_mb)
        return _safe_stub(tests, "MEMORY_LIMIT")
    except OSError as e:
        crash.error("BATCH: не удалось запустить процесс: %s", e)
        return _safe_stub(tests, "RUNNER_ERROR")
    finally:
        stop_event.set()
        if monitor is not None:
            monitor.join(timeout=1.0)
        peak_memory_mb = mem_holder.get("peak_mb", 0.0)

    total_elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    if proc.returncode != 0:
        crash.warning("BATCH: раннер упал rc=%d: %s", proc.returncode, (stderr or "")[:300])
        return _safe_stub(tests, "RUNNER_ERROR")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        crash.error("BATCH: некорректный JSON: %r", (stdout or "")[:200])
        return _safe_stub(tests, "RUNNER_ERROR")

    if not isinstance(data, list):
        return _safe_stub(tests, "RUNNER_ERROR")

    by_id = {x.get("id"): x for x in data if isinstance(x, dict)}

    # Приблизительное время на 1 тест: суммарное / число тестов.
    # Для точности — надо править _RUNNER_TEMPLATE (внутренний замер).
    per_test_ms = total_elapsed_ms / max(len(tests), 1)

    result: list[dict] = []
    for t in tests:
        r = by_id.get(t["id"])
        if r is None:
            result.append({
                "id": t["id"], "out": "", "rc": -1, "err": "MISSING",
                "time_ms": 0.0, "memory_mb": 0.0,
            })
            continue
        result.append({
            "id": t["id"],
            "out": r.get("out", "") or "",
            "rc": int(r.get("rc", -1)),
            "err": r.get("err", "") or "",
            "time_ms": per_test_ms,
            "memory_mb": peak_memory_mb,
        })

    # Логирование для отладки (пойдёт в session.log через QueueHandler)
    for r in result:
        log.info("Тест #%s: rc=%s, time=%.1fms, mem=%.1fMB",
                 r["id"], r["rc"], r["time_ms"], r["memory_mb"])

    return result