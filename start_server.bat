@echo off
chcp 65001 >nul
title Запуск сервера Python vs Sport

:: --- Проверка прав администратора ---
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ============================================================
    echo   ТРЕБУЮТСЯ ПРАВА АДМИНИСТРАТОРА
    echo ============================================================
    echo   Для корректной работы сервера и открытия портов
    echo   брандмауэра, чтобы подключались телефоны, нужны
    echo   права администратора.
    echo.
    echo   Сейчас появится окно запроса прав. Нажмите "Да".
    echo.
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: --- Мы в режиме администратора ---
cd /d "%~dp0"

echo ============================================================
echo   ЗАПУСК СЕРВЕРА PYTHON VS SPORT
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Не найдено виртуальное окружение .venv!
    pause
    exit /b 1
)

if not exist "web\run.py" (
    echo [ОШИБКА] Не найден файл web\run.py!
    pause
    exit /b 1
)

echo [ИНФО] Запускаем сервер...
echo [ИНФО] Для остановки нажмите Ctrl+C.
echo.

cd web
"..\.venv\Scripts\python.exe" run.py

echo.
echo Сервер остановлен.
pause
exit /b 0