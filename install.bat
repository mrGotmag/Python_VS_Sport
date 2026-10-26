@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM  install.bat — установка и обновление проекта Python vs Спорт
REM ============================================================

set "REPO_URL=https://github.com/mrGotmag/Python_VS_Sport.git"
set "PROJECT_DIR=Python_VS_Sport"
set "PYTHON_MIN=3.10"

echo.
echo ============================================================
echo   Установка / Обновление проекта Python vs Спорт
echo ============================================================
echo.

REM ---- 1) Проверка Python ----
echo [1/6] Проверка Python...
where python >nul 2>nul
if errorlevel 1 (
    echo   [ОШИБКА] Python не найден в PATH.
    goto :fail
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo   Найден Python !PY_VER!
echo   OK: версия подходит.

REM ---- 2) Проверка git ----
echo.
echo [2/6] Проверка git...
where git >nul 2>nul
if errorlevel 1 (
    echo   [ОШИБКА] git не найден в PATH.
    goto :fail
)
echo   OK: git найден.

REM ---- 3) Клонирование и СИНХРОНИЗАЦИЯ ----
echo.
echo [3/6] Синхронизация файлов с GitHub...
if exist "%PROJECT_DIR%\.git" (
    echo   Папка %PROJECT_DIR% существует. Обновляем файлы...
    pushd "%PROJECT_DIR%"
    
    git stash >nul 2>&1
    git fetch --all
    if errorlevel 1 (
        echo   [ОШИБКА] Не удалось связаться с GitHub.
        goto :fail_after_pushd
    )
    
    REM Сбрасываем к состоянию репозитория
    git reset --hard origin/main >nul 2>&1
    if errorlevel 1 git reset --hard origin/master >nul 2>&1
    
    REM Удаляем лишние файлы, НО сохраняем .venv и .env
    git clean -fd -e .venv -e .env >nul 2>&1
    
    echo   OK: Файлы синхронизированы.
    popd
) else if exist "%PROJECT_DIR%" (
    echo   [ОШИБКА] Папка %PROJECT_DIR% уже есть, но это не git-репозиторий.
    goto :fail
) else (
    git clone "%REPO_URL%" "%PROJECT_DIR%"
    if errorlevel 1 (
        echo   [ОШИБКА] git clone не удался.
        goto :fail
    )
    echo   OK: Репозиторий склонирован.
)

pushd "%PROJECT_DIR%"

REM ---- 4) Создание venv ----
echo.
echo [4/6] Проверка виртуального окружения .venv...
if exist ".venv\Scripts\python.exe" (
    echo   .venv уже существует.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo   [ОШИБКА] Не удалось создать .venv.
        goto :fail_after_pushd
    )
)
echo   OK.

REM ---- 5) Установка зависимостей ----
echo.
echo [5/6] Установка зависимостей...
if not exist "requirements.txt" (
    echo   [ПРЕДУПРЕЖДЕНИЕ] requirements.txt не найден.
) else (
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
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
    echo   [ПРЕДУПРЕЖДЕНИЕ] Нет .env и .env.example.
)

REM ---- Проверка ----
echo.
echo ============================================================
echo   Проверка установки
echo ============================================================
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, jwt, bcrypt, markdown; print('Все зависимости успешно установлены!')"
if errorlevel 1 goto :fail_after_pushd

echo.
echo ============================================================
echo   ГОТОВО!
echo ============================================================
echo.
echo   Дальше:
echo     cd %PROJECT_DIR%\web
echo     ..\.venv\Scripts\activate
echo     python run.py
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
