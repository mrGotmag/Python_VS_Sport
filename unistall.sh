#!/usr/bin/env bash
set -uo pipefail

# Цвета
C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'; C_CYN=$'\033[36m'; C_RST=$'\033[0m'
info()  { echo "${C_CYN}$*${C_RST}"; }
ok()    { echo "${C_GRN}  OK: $*${C_RST}"; }
warn()  { echo "${C_YLW}  [ВНИМАНИЕ] $*${C_RST}" >&2; }

cd "$(dirname "$0")" || exit

# --- Проверка: запущен ли скрипт изнутри проекта? ---
if [ -d "web" ] && [ -d "orcestrator" ]; then
    info "Скрипт запущен изнутри папки проекта."
    CURRENT_DIR=$(pwd)
    cd ..
    PROJECT_DIR=$(basename "$CURRENT_DIR")
else
    PROJECT_DIR="Python_VS_Sport"
fi

echo
info "============================================================"
info "  УДАЛЕНИЕ ПРОЕКТА PYTHON VS SPORT"
info "============================================================"
echo

warn "Это действие полностью удалит папку '$PROJECT_DIR'."
warn "Вся база данных и задачи будут УДАЛЕНЫ безвозвратно!"
echo

read -r -p "Вы уверены, что хотите удалить проект? [y/N]: " ANSWER
if [[ "${ANSWER,,}" != "y" ]]; then
    echo "Удаление отменено."
    exit 0
fi

echo
info "[1/2] Останавливаем работающие процессы сервера..."
pkill -f "run.py" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
ok "Процессы остановлены."

info "[2/2] Удаляем папку проекта..."
if [ -d "$PROJECT_DIR" ]; then
    rm -rf "$PROJECT_DIR"
    ok "Папка $PROJECT_DIR удалена."
else
    warn "Папка $PROJECT_DIR не найдена."
fi

echo
info "============================================================"
info "  УДАЛЕНИЕ ЗАВЕРШЕНО УСПЕШНО"
info "============================================================"
echo