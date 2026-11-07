@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM --- Переход в папку, где лежит этот скрипт ---
cd /d "%~dp0"

set "PROJECT_DIR=Python_VS_Sport"
set "ZIP_URL=https://github.com/mrGotmag/Python_VS_Sport/archive/refs/heads/main.zip"

echo.
echo ============================================================
echo   Установка / Обновление проекта Python vs Sport
echo ============================================================
echo.

REM ---- 1) Проверка Python 3.12 ----
echo [1/5] Проверка Python 3.12
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"

if exist "%PYTHON_EXE%" goto :python_ok

echo   Python 3.12 не найден. Скачиваем
set "PY_INSTALLER=%TEMP%\python_install.exe"
curl -L -o "%PY_INSTALLER%" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

if not exist "%PY_INSTALLER%" (
    echo ОШИБКА: Не удалось скачать установщик Python.
    pause
    exit /b 1
)

echo   Устанавливаем Python 3.12, это займет пару минут
start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 Include_launcher=1
del /q "%PY_INSTALLER%"

echo   Ждем 3 секунды
timeout /t 3 /nobreak >nul

if not exist "%PYTHON_EXE%" (
    echo [ОШИБКА] Python установился, но файл не найден по пути:
    echo %PYTHON_EXE%
    pause
    exit /b 1
)

:python_ok
echo   OK: Python 3.12 готов.

REM ---- 2) Скачивание файлов проекта ----
echo.
echo [2/5] Скачивание файлов с GitHub

set "ZIP_FILE=%TEMP%\project.zip"
set "EXTRACT_DIR=%TEMP%\project_extracted"

if exist "%EXTRACT_DIR%" rmdir /S /Q "%EXTRACT_DIR%"
mkdir "%EXTRACT_DIR%"

echo   Скачиваем архив, пожалуйста подождите
curl -L -o "%ZIP_FILE%" "%ZIP_URL%"

if not exist "%ZIP_FILE%" (
    echo [ОШИБКА] Не удалось скачать архив. Проверьте интернет.
    pause
    exit /b 1
)

echo   Распаковываем во временную папку
tar -xf "%ZIP_FILE%" -C "%EXTRACT_DIR%"

if not exist "%EXTRACT_DIR%\Python_VS_Sport-main" (
    echo [ОШИБКА] Архив скачался, но папка Python_VS_Sport-main не найдена.
    pause
    exit /b 1
)

REM ---- 3) Умное обновление или чистая установка ----
if exist "%PROJECT_DIR%" (
    echo.
    echo   [ИНФО] Обнаружена существующая папка %PROJECT_DIR%.
    echo   [ИНФО] Обновляем файлы кода, сохраняя вашу базу данных и настройки.
    robocopy "%EXTRACT_DIR%\Python_VS_Sport-main" "%PROJECT_DIR%" /E /XF "contest_web.db" ".env" /XD ".venv" ".git" >nul
    echo   OK: Файлы кода обновлены. Ваша база данных не тронута.
)

if not exist "%PROJECT_DIR%" (
    echo.
    echo   [ИНФО] Выполняется чистая установка.
    ren "%EXTRACT_DIR%\Python_VS_Sport-main" "%PROJECT_DIR%"
    
    if exist "%PROJECT_DIR%\web\contest_web.db" (
        echo.
        echo   [ВНИМАНИЕ] Обнаружена база данных web\contest_web.db, скачанная с GitHub.
        set /p "DEL_DB=  Удалить её для чистой установки? [y/n]: "
        if /I "!DEL_DB!"=="y" (
            del /q "%PROJECT_DIR%\web\contest_web.db"
            echo   OK: База данных удалена.
        )
    )
)

rmdir /S /Q "%EXTRACT_DIR%"
del /q "%ZIP_FILE%"

cd "%PROJECT_DIR%"

REM ---- 4) Создание venv ----
echo.
echo [4/5] Проверка папки .venv

set "VENV_EXISTS=0"
if exist ".venv\Scripts\python.exe" set "VENV_EXISTS=1"

if "!VENV_EXISTS!"=="1" (
    echo   Окружение .venv уже существует. Пропускаем создание.
)

if "!VENV_EXISTS!"=="0" (
    echo   Создаем новый .venv, пожалуйста подождите.
    "%PYTHON_EXE%" -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Не удалось создать .venv.
    pause
    exit /b 1
)
echo   OK: .venv готово.

REM ---- 5) Установка зависимостей ----
echo.
echo [5/5] Установка зависимостей
if exist "requirements.txt" (
    ".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --only-binary=:all:
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить зависимости.
        pause
        exit /b 1
    )
    echo   OK: зависимости установлены.
)

if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo   OK: .env создан.
    )
)

if exist ".env" (
    echo   .env существует, сохранен.
)

echo.
echo Проверка импортов.
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, jwt, bcrypt, markdown, psutil, pydantic_settings, dotenv; print('OK')"
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
echo   Запускаем сервер, браузер откроется автоматически.

cd web
start "Python vs Sport Server" cmd /k "..\.venv\Scripts\python.exe run.py"
cd ..

cd ..
echo.
echo Готово. Нажмите любую клавишу, чтобы закрыть это окно.
pause
exit /b 0
