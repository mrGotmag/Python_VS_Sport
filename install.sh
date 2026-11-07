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
    elif command -v brew >/dev/null 2>&1; then
        info "Обнаружен macOS (Homebrew). Устанавливаем зависимости..."
        brew install curl git gcc make patch openssl readline sqlite3 xz zlib || warn "Некоторые пакеты brew не установились..."
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
    fi

    export PATH="$HOME/.pyenv/bin:$PATH"
    eval "$(pyenv init -)"

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

    # --- БЭКАП БАЗЫ ДАННЫХ И ЗАДАЧ ---
    BACKUP_DIR="${PROJECT_DIR}_backup"
    mkdir -p "$BACKUP_DIR"

    if [ -f "${PROJECT_DIR}/web/contest_web.db" ]; then
        cp "${PROJECT_DIR}/web/contest_web.db" "$BACKUP_DIR/"
        ok "База данных сохранена."
    fi
    if [ -f "${PROJECT_DIR}/.env" ]; then
        cp "${PROJECT_DIR}/.env" "$BACKUP_DIR/"
    fi

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

    if [ "$SYNC_TASKS" -eq 0 ]; then
        # Сохраняем задачи, если не хотим синхронизировать
        mkdir -p "$BACKUP_DIR/orcestrator"
        cp -r "${PROJECT_DIR}/orcestrator/tasks" "$BACKUP_DIR/orcestrator/"
    fi

    cd "${PROJECT_DIR}"

    # ИСПРАВЛЕНИЕ: Добавили исключение для contest_web.db, чтобы git clean не убил базу
    if [ "$SYNC_TASKS" -eq 1 ]; then
        git fetch --all >/dev/null 2>&1 || warn "Не удалось связаться с GitHub"
        git reset --hard origin/main >/dev/null 2>&1 || git reset --hard origin/master >/dev/null 2>&1
        git clean -fd -e .venv -e .env -e web/contest_web.db >/dev/null 2>&1 || true
        ok "Файлы обновлены (включая tasks)"
    else
        echo "  Сохраняем папку tasks..."
        git rm -r --cached --ignore-unmatch "orcestrator/tasks" >/dev/null 2>&1 || true
        git fetch --all >/dev/null 2>&1 || warn "Не удалось связаться с GitHub"
        git reset --hard origin/main >/dev/null 2>&1 || git reset --hard origin/master >/dev/null 2>&1
        git checkout origin/main -- "orcestrator/tasks" >/dev/null 2>&1 || \
            git checkout origin/master -- "orcestrator/tasks" >/dev/null 2>&1 || true
        git clean -fd -e .venv -e .env -e web/contest_web.db -e orcestrator/tasks >/dev/null 2>&1 || true
        ok "Файлы обновлены (папка tasks сохранена)"
    fi

    # Восстанавливаем базу данных и настройки
    if [ -f "$BACKUP_DIR/contest_web.db" ]; then
        cp "$BACKUP_DIR/contest_web.db" "web/contest_web.db"
        ok "База данных восстановлена."
    fi
    if [ -f "$BACKUP_DIR/.env" ]; then
        cp "$BACKUP_DIR/.env" ".env"
    fi
    if [ "$SYNC_TASKS" -eq 0 ] && [ -d "$BACKUP_DIR/orcestrator/tasks" ]; then
        cp -r "$BACKUP_DIR/orcestrator/tasks/"* "orcestrator/tasks/" 2>/dev/null || true
    fi

    rm -rf "$BACKUP_DIR"
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

# ---- Выдача прав на запуск ----
if [ -f "start_server.sh" ]; then
    chmod +x start_server.sh
    ok "Права на запуск start_server.sh установлены."
fi

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
    # ИСПРАВЛЕНИЕ: Убрали --only-binary=:all:, чтобы не падало на Apple Silicon (M1/M2/M3)
    "$VENV_PY" -m pip install -r requirements.txt || fail "Не удалось установить зависимости"
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
"$VENV_PY" -c "import fastapi, uvicorn, sqlalchemy, jwt, bcrypt, markdown, psutil, pydantic_settings, dotenv; print('Все зависимости успешно установлены!')" || fail "Проверка импортов не прошла"

# ---- Запуск ----
echo
info "============================================================"
info "  ЗАПУСК СЕРВЕРА"
info "============================================================"
echo "  Установка завершена! Запускаем сервер с правами администратора..."
echo

# Убедимся, что мы в корне проекта (где лежит start_server.sh)
cd "$(dirname "$0")" 2>/dev/null || true

if [ -f "start_server.sh" ]; then
    # Запускаем наш стартер, который запросит пароль sudo
    ./start_server.sh
else
    warn "Файл start_server.sh не найден! Запускаем сервер напрямую."
    cd web
    "../.venv/bin/python" run.py
fi