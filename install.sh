#!/usr/bin/env bash
# ============================================================
#  install.sh — Установка и запуск проекта Python vs Sport
# ============================================================
set -uo pipefail

REPO_URL="https://github.com/mrGotmag/Python_VS_Sport.git"
PROJECT_DIR="Python_VS_Sport"
PYTHON_VERSION="3.12.10"

# ---- Цвета ----
if [ -t 1 ]; then
    C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'; C_CYN=$'\033[36m'; C_RST=$'\033[0m'
else
    C_RED=""; C_GRN=""; C_YLW=""; C_CYN=""; C_RST=""
fi

info()  { echo "${C_CYN}$*${C_RST}"; }
ok()    { echo "${C_GRN}  OK: $*${C_RST}"; }
warn()  { echo "${C_YLW}  [ПРЕДУПРЕЖДЕНИЕ] $*${C_RST}" >&2; }
fail()  { echo "${C_RED}  [ОШИБКА] $*${C_RST}" >&2; exit 1; }

echo
info "============================================================"
info "  Установка проекта Python vs Sport"
info "============================================================"
echo

# ---- 0) Проверка базовых утилит ----
info "[0/6] Проверка базовых утилит..."

if ! command -v curl >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1 || ! command -v gcc >/dev/null 2>&1 || ! command -v make >/dev/null 2>&1; then
    info "Устанавливаем минимальный набор для сборки..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y curl git build-essential patch \
            libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
            libffi-dev liblzma-dev libncurses-dev || warn "Некоторые пакеты не установились, но пробуем продолжить..."
    else
        fail "Установите curl, git, gcc, make и patch вручную."
    fi
fi
ok "Базовые утилиты готовы."

# ---- 1) Проверка Python 3.12 ----
info "[1/6] Проверка Python 3.12..."
PYTHON_BIN=""
if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
elif [ -f "$HOME/.pyenv/versions/$PYTHON_VERSION/bin/python" ]; then
    PYTHON_BIN="$HOME/.pyenv/versions/$PYTHON_VERSION/bin/python"
else
    warn "Python 3.12 не найден."
    info "Устанавливаем Python 3.12 через pyenv (локально, без sudo)..."
    info "Это займет 3-5 минут, так как Python компилируется из исходников."

    if [ ! -d "$HOME/.pyenv" ]; then
        curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash
        export PATH="$HOME/.pyenv/bin:$PATH"
        eval "$(pyenv init -)"
    else
        export PATH="$HOME/.pyenv/bin:$PATH"
        eval "$(pyenv init -)"
    fi

    if ! pyenv install -s "$PYTHON_VERSION"; then
        fail "Не удалось собрать Python 3.12. Проверьте логи выше."
    fi
    PYTHON_BIN="$HOME/.pyenv/versions/$PYTHON_VERSION/bin/python"
fi

"$PYTHON_BIN" --version || fail "Не удалось запустить Python."
ok "Найден $($PYTHON_BIN --version)"

# ---- 2) Проверка git ----
info "[2/6] Проверка git..."
command -v git >/dev/null 2>&1 || fail "git не найден."
ok "git найден"

# ---- 3) Клонирование ----
info "[3/6] Синхронизация файлов с GitHub..."
if [ -d "${PROJECT_DIR}/.git" ]; then
    echo "  Папка ${PROJECT_DIR} существует. Обновляем..."

    # Спрашиваем, синхронизировать ли папку tasks
    SYNC_TASKS=0
    if [ -d "${PROJECT_DIR}/orcestrator/tasks" ]; then
        echo
        echo "  Обнаружена папка с задачами:"
        echo "    ${PROJECT_DIR}/orcestrator/tasks"
        echo
        echo "  ВНИМАНИЕ: синхронизация с GitHub перезапишет и/или"
        echo "  удалит файлы задач, которых нет в репозитории."
        echo "  Если вы добавляли задачи вручную — выберите 'n',"
        echo "  чтобы сохранить их."
        echo
        read -r -p "  Синхронизировать папку tasks с GitHub? (y/n): " ANSWER
        if [[ "${ANSWER,,}" == "y" ]]; then
            SYNC_TASKS=1
        fi
        echo
    else
        echo "  Папки tasks нет — синхронизируем всё."
        SYNC_TASKS=1
    fi

    cd "${PROJECT_DIR}"

    if [ "$SYNC_TASKS" -eq 1 ]; then
        # Полная синхронизация, как раньше
        git fetch --all >/dev/null 2>&1 || warn "Не удалось связаться с GitHub"
        git reset --hard origin/main >/dev/null 2>&1 || git reset --hard origin/master >/dev/null 2>&1
        git clean -fd -e .venv -e .env >/dev/null 2>&1 || true
        ok "Файлы обновлены (включая tasks)"
    else
        # --- Сохраняем папку tasks ---
        echo "  Сохраняем папку tasks..."

        # 1) Временно убираем tasks из индекса
        git rm -r --cached --ignore-unmatch "orcestrator/tasks" >/dev/null 2>&1 || true

        # 2) Обновляем всё остальное
        git fetch --all >/dev/null 2>&1 || warn "Не удалось связаться с GitHub"
        git reset --hard origin/main >/dev/null 2>&1 || git reset --hard origin/master >/dev/null 2>&1

        # 3) Восстанавливаем индекс для tasks из origin (локальные файлы не трогаются)
        git checkout origin/main -- "orcestrator/tasks" >/dev/null 2>&1 || \
            git checkout origin/master -- "orcestrator/tasks" >/dev/null 2>&1 || true

        # 4) Чистим всё, кроме tasks, .venv, .env
        git clean -fd -e .venv -e .env -e orcestrator/tasks >/dev/null 2>&1 || true

        ok "Файлы обновлены (папка tasks сохранена)"
    fi

    cd ..
else
    if [ -e "${PROJECT_DIR}" ]; then
        echo "  Удаляем старую папку..."
        rm -rf "${PROJECT_DIR}"
    fi
    git clone "${REPO_URL}" "${PROJECT_DIR}" || fail "git clone не удался"
    ok "Репозиторий склонирован"
fi

cd "${PROJECT_DIR}"

# ---- 4) Создание venv ----
info "[4/6] Создание .venv..."
if [ -x ".venv/bin/python" ]; then
    echo "  Удаляем старый .venv..."
    rm -rf .venv
fi

"$PYTHON_BIN" -m venv .venv || fail "Не удалось создать .venv."
VENV_PY=".venv/bin/python"
ok "venv готов"

# ---- 5) Установка зависимостей ----
info "[5/6] Установка зависимостей (это может занять пару минут)..."
if [ -f "requirements.txt" ]; then
    "$VENV_PY" -m pip install --upgrade pip setuptools wheel -q
    "$VENV_PY" -m pip install -r requirements.txt --only-binary=:all: || fail "Не удалось установить зависимости"
    ok "зависимости установлены"
else
    warn "requirements.txt не найден!"
fi

# ---- 6) .env ----
info "[6/6] Подготовка .env..."
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    ok "Создан .env"
fi

# ---- Проверка ----
"$VENV_PY" -c "import fastapi, uvicorn, sqlalchemy, jwt, bcrypt, markdown; print('Все зависимости успешно установлены!')" || fail "Проверка не прошла"

# ---- Запуск ----
echo
info "============================================================"
info "  ЗАПУСК СЕРВЕРА"
info "============================================================"
echo "  Сервер запускается. Для остановки нажмите Ctrl+C."
echo

cd web

# Открываем браузер в фоне
( sleep 2 && (xdg-open "http://localhost:8000" 2>/dev/null || open "http://localhost:8000" 2>/dev/null || echo "Откройте http://localhost:8000 вручную") ) &

# Запускаем сервер
"../${VENV_PY}" run.py