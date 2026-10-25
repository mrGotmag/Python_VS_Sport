@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM  install.bat — установка проекта Contest/orchestrator
REM ============================================================

REM ---- НАСТРОЙКИ (поменяйте под себя) ----
set "REPO_URL=https://github.com/USER/REPO.git"
set "PROJECT_DIR=orchestrator"
set "PYTHON_MIN=3.10"
REM ----------------------------------------

echo.
echo ============================================================
echo   Установка проекта
echo   Репозиторий: %REPO_URL%
echo   Папка:       %PROJECT_DIR%
echo ============================================================
echo.

REM ---- 1) Проверка Python ----
echo [1/6] Проверка Python...
where python >nul 2>nul
if errorlevel 1 (
    echo   [ОШИБКА] Python не найден в PATH.
    echo   Установите Python %PYTHON_MIN%+ с https://www.python.org/downloads/
    echo   При установке отметьте "Add Python to PATH".
    goto :fail
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo   Найден Python !PY_VER!

REM Проверка версии (грубая, по первым двум числам)
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)
if !PY_MAJOR! LSS 3 (
    echo   [ОШИБКА] Нужен Python %PYTHON_MIN%+, найден !PY_VER!
    goto :fail
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 10 (
    echo   [ОШИБКА] Нужен Python %PYTHON_MIN%+, найден !PY_VER!
    goto :fail
)
echo   OK: версия подходит.

REM ---- 2) Проверка git ----
echo.
echo [2/6] Проверка git...
where git >nul 2>nul
if errorlevel 1 (
    echo   [ОШИБКА] git не найден в PATH.
    echo   Установите Git for Windows: https://git-scm.com/download/win
    goto :fail
)
echo   OK: git найден.

REM ---- 3) Клонирование ----
echo.
echo [3/6] Клонирование репозитория...
if exist "%PROJECT_DIR%\.git" (
    echo   Папка %PROJECT_DIR% уже существует, делаем git pull...
    pushd "%PROJECT_DIR%"
    git pull
    if errorlevel 1 (
        echo   [ПРЕДУПРЕЖДЕНИЕ] git pull не удался, продолжаем с текущей версией.
    )
    popd
) else if exist "%PROJECT_DIR%" (
    echo   [ОШИБКА] Папка %PROJECT_DIR% уже есть, но это не git-репозиторий.
    echo   Удалите её вручную и запустите снова.
    goto :fail
) else (
    git clone "%REPO_URL%" "%PROJECT_DIR%"
    if errorlevel 1 (
        echo   [ОШИБКА] git clone не удался. Проверьте URL и доступ к сети.
        goto :fail
    )
)

pushd "%PROJECT_DIR%"
if errorlevel 1 (
    echo   [ОШИБКА] Не удалось перейти в %PROJECT_DIR%.
    goto :fail
)

REM ---- 4) Создание venv ----
echo.
echo [4/6] Создание виртуального окружения .venv...
if exist ".venv\Scripts\python.exe" (
    echo   .venv уже существует, используем его.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo   [ОШИБКА] Не удалось создать .venv.
        echo   Попробуйте: python -m venv .venv
        goto :fail_after_pushd
    )
)
echo   OK.

REM ---- 5) Установка зависимостей ----
echo.
echo [5/6] Установка зависимостей...
if not exist "requirements.txt" (
    echo   [ПРЕДУПРЕЖДЕНИЕ] requirements.txt не найден, пропускаем.
) else (
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 (
        echo   [ПРЕДУПРЕЖДЕНИЕ] Не удалось обновить pip, продолжаем.
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo   [ОШИБКА] Не удалось установить зависимости.
        goto :fail_after_pushd
    )
    echo   OK.
)

REM ---- 6) .env ----
echo.
echo [6/6] Подготовка .env...
if exist ".env" (
    echo   .env уже существует, не трогаем.
) else if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo   Создан .env из .env.example.
) else (
    echo   [ПРЕДУПРЕЖДЕНИЕ] Нет ни .env, ни .env.example.
    echo   Создайте .env вручную.
)

REM ---- Проверка ----
echo.
echo ============================================================
echo   Проверка установки
echo ============================================================
".venv\Scripts\python.exe" -c "import sys; print('Python:', sys.version.split()[0])"
if errorlevel 1 goto :fail_after_pushd
".venv\Scripts\python.exe" -c "import dotenv; print('python-dotenv: OK')"
if errorlevel 1 goto :fail_after_pushd

echo.
echo ============================================================
echo   ГОТОВО!
echo ============================================================
echo.
echo   Дальше:
echo     cd %PROJECT_DIR%
echo     .venv\Scripts\activate
echo     python main.py tasks --only 1
echo.

popd
endlocal
exit /b 0

:fail_after_pushd
popd

:fail
echo.
echo ============================================================
echo   УСТАНОВКА ПРЕРВАНА
echo ============================================================
endlocal
exit /b 1