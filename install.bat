@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

cd /d "%USERPROFILE%\Desktop"

set "REPO_URL=https://github.com/mrGotmag/Python_VS_Sport.git"
set "PROJECT_DIR=Python_VS_Sport"

echo.
echo ============================================================
echo   Установка проекта Python vs Sport
echo ============================================================
echo.

REM ---- 1) Проверка Python 3.12 ----
echo [1/6] Проверка Python 3.12...

set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"

if exist "%PYTHON_EXE%" (
    echo   Python 3.12 уже установлен по пути: %PYTHON_EXE%
    goto :python_ok
)

echo   Python 3.12 не найден. Скачиваем...
set "PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
set "PY_INSTALLER=%TEMP%\python_install.exe"

if exist "%PY_INSTALLER%" del /q "%PY_INSTALLER%"
curl -L -o "%PY_INSTALLER%" "%PY_URL%"

if not exist "%PY_INSTALLER%" (
    echo ОШИБКА: Не удалось скачать установщик Python.
    pause
    exit /b 1
)

echo   Устанавливаем Python 3.12...
start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 Include_launcher=1
del /q "%PY_INSTALLER%"

echo   Ждем 3 секунды...
timeout /t 3 /nobreak >nul

if not exist "%PYTHON_EXE%" (
    echo [ОШИБКА] Python установился, но файл не найден по пути:
    echo %PYTHON_EXE%
    echo Скорее всего, антивирус заблокировал установку или путь другой.
    pause
    exit /b 1
)

:python_ok
echo   OK: Python 3.12 готов.

REM ---- 2) Проверка git ----
echo.
echo [2/6] Проверка git...

where git >nul 2>nul
if not errorlevel 1 goto :git_ok

echo   Git не найден. Скачиваем...
set "GIT_URL=https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe"
set "GIT_INSTALLER=%TEMP%\git_install.exe"

if exist "%GIT_INSTALLER%" del /q "%GIT_INSTALLER%"
echo   Скачиваем Git...
curl -L -o "%GIT_INSTALLER%" "%GIT_URL%"

if not exist "%GIT_INSTALLER%" (
    echo [ОШИБКА] Не удалось скачать установщик Git.
    pause
    exit /b 1
)

echo   Устанавливаем Git (тихий режим)...
start /wait "" "%GIT_INSTALLER%" /VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS="icons,ext\reg\shellhere,assoc,assoc_sh"
del /q "%GIT_INSTALLER%"

set "PATH=%ProgramFiles%\Git\cmd;%PATH%"

where git >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Git установился, но консоль его не видит.
    pause
    exit /b 1
)

:git_ok
echo   OK: git найден.

REM ---- 3) Клонирование и СИНХРОНИЗАЦИЯ ----
echo.
echo [3/6] Синхронизация файлов с GitHub...

REM Флаг: синхронизировать ли папку tasks (1 = да, 0 = нет)
set "SYNC_TASKS=0"

if exist "%PROJECT_DIR%\.git" (
    echo   Папка существует. Обновляем...

    REM --- Спрашиваем, синхронизировать ли папку tasks ---
    set "TASKS_DIR_EXISTS=0"
    if exist "%PROJECT_DIR%\orcestrator\tasks" set "TASKS_DIR_EXISTS=1"

    if "!TASKS_DIR_EXISTS!"=="1" (
        echo.
        echo   Обнаружена папка с задачами:
        echo     %PROJECT_DIR%\orcestrator\tasks
        echo.
        echo   ВНИМАНИЕ: синхронизация с GitHub перезапишет и/или
        echo   удалит файлы задач, которых нет в репозитории.
        echo   Если вы добавляли задачи вручную — выберите "n",
        echo   чтобы сохранить их.
        echo.
        set /p "SYNC_TASKS_ANSWER=  Синхронизировать папку tasks с GitHub? (y/n): "
        if /I "!SYNC_TASKS_ANSWER!"=="y" set "SYNC_TASKS=1"
        echo.
    ) else (
        echo   Папки tasks нет — синхронизируем всё.
        set "SYNC_TASKS=1"
    )

    cd "%PROJECT_DIR%"

    if "!SYNC_TASKS!"=="1" (
        REM Полная синхронизация, как раньше
        git fetch --all >nul 2>&1
        git reset --hard origin/main >nul 2>&1
        git clean -fd -e .venv -e .env >nul 2>&1
        echo   OK: файлы обновлены (включая tasks).
    ) else (
        REM --- Сохраняем папку tasks ---
        echo   Сохраняем папку tasks...

        REM 1) Временно убираем tasks из индекса git, чтобы reset --hard не тронул
        git rm -r --cached --ignore-unmatch "orcestrator/tasks" >nul 2>&1

        REM 2) Обновляем всё остальное
        git fetch --all >nul 2>&1
        git reset --hard origin/main >nul 2>&1

        REM 3) Восстанавливаем индекс для tasks из origin (если там были файлы),
        REM    но локальные файлы не трогаем
        git checkout origin/main -- "orcestrator/tasks" >nul 2>&1

        REM 4) Чистим всё, КРОМЕ tasks, .venv, .env
        git clean -fd -e .venv -e .env -e orcestrator/tasks >nul 2>&1

        echo   OK: файлы обновлены (папка tasks сохранена).
    )

    cd ..
    goto :check_venv
)

if exist "%PROJECT_DIR%" (
    echo   Удаляем старую папку...
    rmdir /S /Q "%PROJECT_DIR%"
)

echo   Клонируем репозиторий...
git clone "%REPO_URL%" "%PROJECT_DIR%"
if errorlevel 1 (
    echo [ОШИБКА] Не удалось клонировать репозиторий. Проверьте интернет.
    pause
    exit /b 1
)
echo   OK: репозиторий склонирован.

:check_venv
cd "%PROJECT_DIR%"
echo.
echo [4/6] Проверка .venv...

if exist ".venv\Scripts\python.exe" (
    echo   Удаляем старый .venv для чистой установки...
    rmdir /S /Q ".venv"
)

echo   Создаем новый .venv (пожалуйста, подождите)...
"%PYTHON_EXE%" -m venv .venv

if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Не удалось создать .venv.
    pause
    exit /b 1
)
echo   OK: .venv создано.

echo.
echo [5/6] Установка зависимостей (займет 1-2 минуты)...
if exist "requirements.txt" (
    ".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --only-binary=:all:

    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить зависимости.
        pause
        exit /b 1
    )
    echo   OK: зависимости установлены.
) else (
    echo   ВНИМАНИЕ: requirements.txt не найден.
)

echo.
echo [6/6] Подготовка .env...
if exist ".env" (
    echo   .env существует.
) else if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo   OK: .env создан.
)

echo.
echo Проверка импортов...
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, jwt, bcrypt, markdown; print('OK')"
if errorlevel 1 (
    echo [ОШИБКА] Зависимости не установились.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   ЗАПУСК СЕРВЕРА
echo ============================================================
echo.
echo   Открываем браузер и запускаем сервер...

cd web
start "" explorer "http://localhost:8000"
start "Python vs Sport Server" cmd /k "..\.venv\Scripts\python.exe run.py"
cd ..

cd ..
echo.
echo Установка завершена. Нажмите любую клавишу, чтобы закрыть это окно.
pause
exit /b 0