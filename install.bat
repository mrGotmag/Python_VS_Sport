@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PROJECT_DIR=Python_VS_Sport"
set "ZIP_URL=https://github.com/mrGotmag/Python_VS_Sport/archive/refs/heads/main.zip"

echo ============================================================
echo   Установка / Обновление проекта Python vs Sport
echo ============================================================
echo.

echo [1/5] Проверка Python 3.12
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
if exist "%PYTHON_EXE%" goto python_ok

echo Python 3.12 не найден. Скачиваем...
set "PY_INSTALLER=%TEMP%\python_install.exe"
curl -L -o "%PY_INSTALLER%" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
if not exist "%PY_INSTALLER%" (
    echo ОШИБКА: Не удалось скачать установщик Python.
    pause
    exit /b 1
)

echo Устанавливаем Python 3.12, это займет пару минут...
start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 Include_launcher=1
del /q "%PY_INSTALLER%"
timeout /t 3 /nobreak >nul

if not exist "%PYTHON_EXE%" (
    echo [ОШИБКА] Python установился, но файл не найден по пути:
    echo %PYTHON_EXE%
    pause
    exit /b 1
)

:python_ok
echo OK: Python 3.12 готов.

echo.
echo [2/5] Скачивание файлов с GitHub
set "ZIP_FILE=%TEMP%\project.zip"
set "EXTRACT_DIR=%TEMP%\project_extracted"
if exist "%EXTRACT_DIR%" rmdir /S /Q "%EXTRACT_DIR%"
mkdir "%EXTRACT_DIR%"

echo Скачиваем архив, пожалуйста подождите...
curl -L -o "%ZIP_FILE%" "%ZIP_URL%"
if not exist "%ZIP_FILE%" (
    echo [ОШИБКА] Не удалось скачать архив. Проверьте интернет.
    pause
    exit /b 1
)

echo Распаковываем во временную папку...
tar -xf "%ZIP_FILE%" -C "%EXTRACT_DIR%"
if not exist "%EXTRACT_DIR%\Python_VS_Sport-main" (
    echo [ОШИБКА] Архив скачался, но папка Python_VS_Sport-main не найдена.
    pause
    exit /b 1
)

if exist "%PROJECT_DIR%" goto update_files
goto clean_install

:update_files
echo.
echo [ИНФО] Обнаружена существующая папка %PROJECT_DIR%.
echo [ИНФО] Обновляем файлы кода, сохраняя вашу базу данных и настройки...
robocopy "%EXTRACT_DIR%\Python_VS_Sport-main" "%PROJECT_DIR%" /E /XF "contest_web.db" ".env" /XD ".venv" ".git" >nul
echo OK: Файлы кода обновлены. Ваша база данных не тронута.
goto clean_temp

:clean_install
echo.
echo [ИНФО] Выполняется чистая установка...
ren "%EXTRACT_DIR%\Python_VS_Sport-main" "%PROJECT_DIR%"
if not exist "%PROJECT_DIR%\web\contest_web.db" goto clean_temp

echo.
echo [ВНИМАНИЕ] Обнаружена база данных web\contest_web.db, скачанная с GitHub.
choice /C YN /M "Удалить ее для чистой установки"
if errorlevel 2 goto clean_temp
if errorlevel 1 del /q "%PROJECT_DIR%\web\contest_web.db"
echo OK: База данных удалена.

:clean_temp
rmdir /S /Q "%EXTRACT_DIR%"
del /q "%ZIP_FILE%"
cd "%PROJECT_DIR%"

echo.
echo [4/5] Проверка .venv
if exist ".venv\Scripts\python.exe" goto venv_ok

echo Создаем новый .venv, пожалуйста подождите...
"%PYTHON_EXE%" -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Не удалось создать .venv.
    pause
    exit /b 1
)

:venv_ok
echo OK: .venv готово.

echo.
echo [5/5] Установка зависимостей
if not exist "requirements.txt" goto skip_pip
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt --only-binary=:all:
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
)
echo OK: зависимости установлены.

:skip_pip
if exist ".env" goto skip_env
if not exist ".env.example" goto skip_env
copy /Y ".env.example" ".env" >nul
echo OK: .env создан.

:skip_env
echo Проверка импортов...
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
echo Запускаем сервер, браузер откроется автоматически...

cd web
start "Python vs Sport Server" cmd /k "..\.venv\Scripts\python.exe run.py"
cd ..
cd ..

echo.
echo Готово. Нажмите любую клавишу, чтобы закрыть это окно.
pause
exit /b 0
