from pathlib import Path

from config import settings

MAX_SIZE_BYTES = settings.max_code_size_bytes


class CodeReadError(Exception):
    pass


def read_code(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise CodeReadError(f"Файл не найден: {p}")
    if not p.is_file():
        raise CodeReadError(f"Это не файл: {p}")

    size = p.stat().st_size
    if size == 0:
        raise CodeReadError(f"Файл пустой: {p}")
    if size > MAX_SIZE_BYTES:
        raise CodeReadError(f"Файл слишком большой: {p} ({size} > {MAX_SIZE_BYTES})")

    try:
        # utf-8-sig: читает UTF-8 и корректно пропускает BOM, если он есть
        code = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise CodeReadError(f"Файл не в UTF-8: {p} ({e.reason})") from e

    if not code.strip():
        raise CodeReadError(f"Файл только из пробелов: {p}")
    return code