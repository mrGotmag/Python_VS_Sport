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

_SAFE_IMPORT_CODE = """
import builtins
import sys as _real_sys

ALLOWED = "__ALLOWED__".split()

_original_import = builtins.__import__
_safe_exec = exec
_safe_compile = compile

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root_module = name.split('.')[0]
    if root_module not in ALLOWED:
        raise ImportError(f"Импорт модуля '{root_module}' запрещен правилами олимпиады.")
    return _original_import(name, globals, locals, fromlist, level)

def _safe_open(*args, **kwargs):
    raise PermissionError("Открытие файлов запрещено правилами олимпиады.")

builtins.__import__ = _safe_import
builtins.open = _safe_open

# Вариант B: setrecursionlimit без импорта sys (безопаснее, чем пускать sys)
builtins.setrecursionlimit = _real_sys.setrecursionlimit
builtins.getrecursionlimit = _real_sys.getrecursionlimit
del _real_sys

_DANGEROUS = ("eval", "exec", "compile", "breakpoint", "globals", "locals", "vars")
for _name in _DANGEROUS:
    try:
        delattr(builtins, _name)
    except AttributeError:
        pass
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
                _safe_exec(_safe_compile(code, "<solution>", "exec"), {"__name__": "__main__"})
            out = buf.getvalue()
            if len(out) > MAX_OUTPUT:
                results.append({"id": t["id"], "out": out[:MAX_OUTPUT],
                                "rc": 1, "err": "OUTPUT_LIMIT"})
            else:
                results.append({"id": t["id"], "out": out, "rc": 0, "err": ""})
        except SystemExit as e:
            out = buf.getvalue()
            if e.code in (0, None):
                if len(out) > MAX_OUTPUT:
                    results.append({"id": t["id"], "out": out[:MAX_OUTPUT],
                                    "rc": 1, "err": "OUTPUT_LIMIT"})
                else:
                    results.append({"id": t["id"], "out": out, "rc": 0, "err": ""})
            else:
                results.append({"id": t["id"], "out": out,
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
            _safe_exec(_safe_compile(code, "<solution>", "exec"), {"__name__": "__main__"})
        out = buf.getvalue()
        if len(out) > MAX_OUTPUT:
            return {"out": out[:MAX_OUTPUT], "rc": 1, "err": "OUTPUT_LIMIT"}
        return {"out": out, "rc": 0, "err": ""}
    except SystemExit as e:
        out = buf.getvalue()
        if e.code in (0, None):
            if len(out) > MAX_OUTPUT:
                return {"out": out[:MAX_OUTPUT], "rc": 1, "err": "OUTPUT_LIMIT"}
            return {"out": out, "rc": 0, "err": ""}
        return {"out": out, "rc": 1, "err": f"SystemExit({e.code!r})"}
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

# Формируем безопасный импорт
_safe_import_str = _SAFE_IMPORT_CODE.replace(
    "__ALLOWED__", ALLOWED_IMPORTS_STR
)

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
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
            except (ValueError, OSError):
                pass
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
            except (ValueError, OSError):
                pass
            try:
                resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
            except (ValueError, OSError):
                pass
        except (ImportError, ValueError, OSError):
            pass

    return _limits


def _kill_process_tree(proc) -> None:
    """
    Убивает процесс и всё его дерево. Кросс-платформенно.
    На Windows — taskkill /T, на Unix — psutil.children(recursive=True).
    """
    if proc is None:
        return

    if platform.system() == "Windows":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass

    if HAS_PSUTIL:
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            parent.kill()
            return
        except psutil.Error:
            pass

    try:
        proc.kill()
    except OSError:
        pass


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

    peak_memory_mb = 0.0
    proc = None
    stop_event = threading.Event()
    mem_holder = {"peak_mb": 0.0, "killed_for_memory": False}

    def _tree_rss_mb(p) -> float:
        """Сумма RSS процесса и всех потомков (MB)."""
        try:
            total = p.memory_info().rss
            for child in p.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except psutil.Error:
                    pass
            return total / (1024 * 1024)
        except psutil.Error:
            return 0.0

    def _monitor_memory(pid: int, holder: dict, stop_evt: threading.Event,
                        limit_mb: int, proc_ref) -> None:
        if not HAS_PSUTIL:
            return
        try:
            p = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

        peak = 0.0

        # Первый замер сразу
        peak = _tree_rss_mb(p)

        while not stop_evt.is_set():
            try:
                mem_val = _tree_rss_mb(p)
                if mem_val > peak:
                    peak = mem_val
                if mem_val > limit_mb:
                    crash.warning(
                        "MEMORY LIMIT: %.0f MB > %d MB, убиваю pid=%d",
                        mem_val, limit_mb, pid,
                    )
                    _kill_process_tree(proc_ref)
                    holder["killed_for_memory"] = True
                    break
            except psutil.Error:
                break
            time.sleep(0.01)
        holder["peak_mb"] = peak

    monitor = None

    start_time = time.perf_counter()
    try:
        popen_kwargs = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True
            popen_kwargs["preexec_fn"] = preexec

        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", runner],
            **popen_kwargs,
        )

        if HAS_PSUTIL:
            monitor = threading.Thread(
                target=_monitor_memory,
                args=(proc.pid, mem_holder, stop_event, memory_mb, proc),
                daemon=True,
            )
            monitor.start()

        try:
            stdout, stderr = proc.communicate(input=payload, timeout=total_timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            try:
                proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                crash.error(
                    "BATCH TIMEOUT: процесс не умер после kill (pid=%s)",
                    getattr(proc, "pid", "?"),
                )
            crash.warning(
                "BATCH TIMEOUT (%.1fs) на %d тестов", total_timeout, len(tests)
            )
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

    if mem_holder.get("killed_for_memory"):
        crash.warning("BATCH MEMORY_LIMIT (%d МБ, убит монитором)", memory_mb)
        return _safe_stub(tests, "MEMORY_LIMIT")

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

    for r in result:
        log.info("Тест #%s: rc=%s, time=%.1fms, mem=%.1fMB",
                 r["id"], r["rc"], r["time_ms"], r["memory_mb"])

    return result