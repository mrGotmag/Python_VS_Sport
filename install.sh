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

if ! command -v curl >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
    info "Устанавливаем минимальный набор (curl, git)..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y curl git || warn "Некоторые пакеты не установились, пробуем продолжить..."
    else
        fail "Установите curl и git вручную."
    fi
fi
ok "Базовые утилиты готовы."

# ---- 1) Проверка Python 3.12 (Скачивание или Сборка) ----
info "[1/6] Проверка Python 3.12..."
PYTHON_BIN=""

# 1.1 Ищем системный Python или уже установленный в pyenv
if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
    ok "Найден системный Python 3.12"
elif [ -f "$HOME/.pyenv/versions/$PYTHON_VERSION/bin/python" ]; then
    PYTHON_BIN="$HOME/.pyenv/versions/$PYTHON_VERSION/bin/python"
    ok "Найден Python 3.12 в pyenv"
fi

# 1.2 Если нет — пробуем СКАЧАТЬ готовый бинарник
if [ -z "$PYTHON_BIN" ]; then
    info "Python 3.12 не найден. Пытаемся скачать готовую сборку (без компиляции)..."
    
    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then
        TARGET="x86_64-unknown-linux-gnu"
    elif [ "$ARCH" = "aarch64" ]; then
        TARGET="aarch64-unknown-linux-gnu"
    else
        TARGET=""
    fi

    if [ -n "$TARGET" ]; then
        # Ссылка на скомпилированный Python 3.12.10 от Astral (python-build-standalone)
        DL_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20240415/cpython-3.12.2+20240415-${TARGET}-install_only.tar.gz"
        PY_DIR="$HOME/.local/share/python-standalone"
        
        mkdir -p "$PY_DIR"
        info "Скачиваем архив (около 25 МБ)..."
        
        if curl -fL --connect-timeout 15 -o "$PY_DIR/python.tar.gz" "$DL_URL" 2>/dev/null; then
            info "Распаковываем..."
            tar -xzf "$PY_DIR/python.tar.gz" -C "$PY_DIR"
            PYTHON_BIN="$PY_DIR/python/bin/python3.12"
            
            if [ -x "$PYTHON_BIN" ] && "$PYTHON_BIN" --version >/dev/null 2>&1; then
                ok "Успешно скачан готовый Python 3.12"
            else
                warn "Архив скачался, но не запускается. Откат на компиляцию."
                PYTHON_BIN=""
            fi
        else
            warn "Не удалось скачать бинарник (возможно, блокировка сети)."
        fi
    fi
fi

# 1.3 Если скачать не удалось — СОБИРАЕМ через pyenv (Fallback)
if [ -z "$PYTHON_BIN" ]; then
    warn "Переходим к сборке Python 3.12 из исходников через pyenv..."
    info "Это займет 3-5 минут."
    
    if ! command -v gcc >/dev/null 2>&1 || ! command -v make >/dev/null 2>&1; then
        info "Устанавливаем компилятор и библиотеки для сборки..."
        if command -v apt-get >/dev/null 2>&1; then
            sudo apt-get install -y build-essential libssl-dev zlib1g-dev libbz2-dev \
                libreadline-dev libsqlite3-dev libffi-dev liblzma-dev libncurses-dev || true
        fi
    fi

    if [ ! -d "$HOME/.pyenv" ]; then
        curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash
    fi
    export PATH="$HOME/.pyenv/bin:$PATH"
    eval "$(pyenv init -)"
    
    if ! pyenv install -s "$PYTHON_VERSION"; then
        fail "Не удалось собрать Python 3.12. Не хватает библиотек или прав."
    fi
    PYTHON_BIN="$HOME/.pyenv/versions/$PYTHON_VERSION/bin/python"
fi

"$PYTHON_BIN" --version || fail "Не удалось запустить Python."
ok "Найден $($PYTHON_BIN --version)"

# ---- 2) Проверка git ----
info "[2/6] Проверка git..."
command -v git >/dev/null 2>&1 || fail "git не найден."
ok "git найден"

# ---- 3) Клонирование и СИНХРОНИЗАЦИЯ ----
info "[3/6] Синхронизация файлов с GitHub..."
if [ -d "${PROJECT_DIR}/.git" ]; then
    echo "  Папка ${PROJECT_DIR} существует. Обновляем..."

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
        git fetch --all >/dev/null 2>&1 || warn "Не удалось связаться с GitHub"
        git reset --hard origin/main >/dev/null 2>&1 || git reset --hard origin/master >/dev/null 2>&1
        git clean -fd -e .venv -e .env >/dev/null 2>&1 || true
        ok "Файлы обновлены (включая tasks)"
    else
        echo "  Сохраняем папку tasks..."
        git rm -r --cached --ignore-unmatch "orcestrator/tasks" >/dev/null 2>&1 || true
        git fetch --all >/dev/null 2>&1 || warn "Не удалось связаться с GitHub"
        git reset --hard origin/main >/dev/null 2>&1 || git reset --hard origin/master >/dev/null 2>&1
        git checkout origin/main -- "orcestrator/tasks" >/dev/null 2>&1 || git checkout origin/master -- "orcestrator/tasks" >/dev/null 2>&1 || true
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

( sleep 2 && (xdg-open "http://localhost:8000" 2>/dev/null || open "http://localhost:8000" 2>/dev/null || echo "Откройте http://localhost:8000 вручную") ) &

"../${VENV_PY}" run.py
