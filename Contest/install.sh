#!/usr/bin/env bash
# ============================================================
#  install.sh — установка проекта Contest/orchestrator
# ============================================================
set -euo pipefail

# ---- НАСТРОЙКИ (поменяйте под себя) ----
REPO_URL="https://github.com/USER/REPO.git"
PROJECT_DIR="orchestrator"
PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=10
# ---------------------------------------

# ---- цвета (отключаются, если не TTY) ----
if [ -t 1 ]; then
    C_RED=$'\033[31m'
    C_GRN=$'\033[32m'
    C_YLW=$'\033[33m'
    C_CYN=$'\033[36m'
    C_RST=$'\033[0m'
else
    C_RED=""; C_GRN=""; C_YLW=""; C_CYN=""; C_RST=""
fi

info()  { echo "${C_CYN}$*${C_RST}"; }
ok()    { echo "${C_GRN}  OK: $*${C_RST}"; }
warn()  { echo "${C_YLW}  [ПРЕДУПРЕЖДЕНИЕ] $*${C_RST}" >&2; }
fail()  { echo "${C_RED}  [ОШИБКА] $*${C_RST}" >&2; exit 1; }

echo
info "============================================================"
info "  Установка проекта"
echo "  Репозиторий: ${REPO_URL}"
echo "  Папка:       ${PROJECT_DIR}"
info "============================================================"
echo

# ---- 1) Python ----
info "[1/6] Проверка Python..."

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done

[ -n "$PYTHON_BIN" ] || fail "Python не найден. Установите Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+ (например: sudo apt install python3.10 python3.10-venv)"

PY_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VER%%.*}"
PY_MINOR="${PY_VER##*.}"
echo "  Найден ${PYTHON_BIN} (${PY_VER})"

if [ "$PY_MAJOR" -lt "$PYTHON_MIN_MAJOR" ] || \
   { [ "$PY_MAJOR" -eq "$PYTHON_MIN_MAJOR" ] && [ "$PY_MINOR" -lt "$PYTHON_MIN_MINOR" ]; }; then
    fail "Нужен Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+, найден ${PY_VER}"
fi
ok "версия подходит"

# venv-модуль должен быть доступен (в Debian/Ubuntu — отдельный пакет)
if ! "$PYTHON_BIN" -c "import venv" >/dev/null 2>&1; then
    fail "Модуль venv недоступен. Установите: sudo apt install python${PY_MAJOR}.${PY_MINOR}-venv"
fi
ok "модуль venv доступен"

# ---- 2) git ----
info "[2/6] Проверка git..."
command -v git >/dev/null 2>&1 || fail "git не найден. Установите: sudo apt install git (или brew install git)"
ok "git найден"

# ---- 3) Клонирование ----
info "[3/6] Клонирование репозитория..."
if [ -d "${PROJECT_DIR}/.git" ]; then
    echo "  Папка ${PROJECT_DIR} уже существует, делаем git pull..."
    ( cd "${PROJECT_DIR}" && git pull --ff-only ) || warn "git pull не удался, продолжаем с текущей версией"
elif [ -e "${PROJECT_DIR}" ]; then
    fail "Папка ${PROJECT_DIR} уже есть, но это не git-репозиторий. Удалите её вручную."
else
    git clone "${REPO_URL}" "${PROJECT_DIR}" || fail "git clone не удался. Проверьте URL и доступ к сети."
fi

cd "${PROJECT_DIR}"

# ---- 4) venv ----
info "[4/6] Создание виртуального окружения .venv..."
if [ -x ".venv/bin/python" ]; then
    echo "  .venv уже существует, используем его."
else
    "$PYTHON_BIN" -m venv .venv || fail "Не удалось создать .venv"
fi
VENV_PY=".venv/bin/python"
ok "venv готов"

# ---- 5) зависимости ----
info "[5/6] Установка зависимостей..."
if [ ! -f "requirements.txt" ]; then
    warn "requirements.txt не найден, пропускаем"
else
    "$VENV_PY" -m pip install --upgrade pip || warn "не удалось обновить pip, продолжаем"
    "$VENV_PY" -m pip install -r requirements.txt || fail "Не удалось установить зависимости"
    ok "зависимости установлены"
fi

# ---- 6) .env ----
info "[6/6] Подготовка .env..."
if [ -f ".env" ]; then
    echo "  .env уже существует, не трогаем."
elif [ -f ".env.example" ]; then
    cp .env.example .env
    ok "создан .env из .env.example"
else
    warn "Нет ни .env, ни .env.example. Создайте .env вручную."
fi

# ---- Проверка ----
echo
info "============================================================"
info "  Проверка установки"
info "============================================================"
"$VENV_PY" - <<'PY' || fail "проверка не прошла"
import sys
print(f"  Python: {sys.version.split()[0]}")
try:
    import dotenv
    print("  python-dotenv: OK")
except ImportError:
    print("  python-dotenv: НЕ УСТАНОВЛЕН")
    sys.exit(1)
PY

# ---- Готово ----
echo
info "============================================================"
info "  ГОТОВО!"
info "============================================================"
echo
echo "  Дальше:"
echo "    cd ${PROJECT_DIR}"
echo "    source .venv/bin/activate"
echo "    python main.py tasks --only 1"
echo