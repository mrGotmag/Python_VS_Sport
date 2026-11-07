@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PROJECT_DIR=Python_VS_Sport"
set "TEMP_BACKUP=%~dp0PvS_temp"
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
echo Скачиваем архив...
curl -L -o "%ZIP_FILE%" "%ZIP_URL%"
if not exist "%ZIP_FILE%" (
    echo [ОШИБКА] Не удалось скачать архив. Проверьте интернет.
    pause
    exit /b 1
)

echo Распаковываем архив...
tar -xf "%ZIP_FILE%"
if not exist "Python_VS_Sport-main" (
    echo [ОШИБКА] Папка Python_VS_Sport-main не найдена после распаковки.
    pause
    exit /b 1
)
del /q "%ZIP_FILE%"

echo.
echo [3/5] Обновление файлов и сохранение базы
if exist "%TEMP_BACKUP%" rmdir /S /Q "%TEMP_BACKUP%"

if not exist "%PROJECT_DIR%" goto no_old_project

echo Обнаружена существующая установка. Останавливаем сервер...
taskkill /F /IM python.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

mkdir "%TEMP_BACKUP%"

echo Сохраняем вашу базу данных...
if exist "%PROJECT_DIR%\web\contest_web.db" (
    mkdir "%TEMP_BACKUP%\web"
    copy /Y "%PROJECT_DIR%\web\contest_web.db" "%TEMP_BACKUP%\web\contest_web.db" >nul
)

echo Сохраняем настройки .env...
if exist "%PROJECT_DIR%\.env" (
    copy /Y "%PROJECT_DIR%\.env" "%TEMP_BACKUP%\.env" >nul
)

echo.
choice /C YN /M "Синхронизировать папку задач tasks с GitHub"
if errorlevel 2 goto skip_tasks
if errorlevel 1 goto copy_tasks

:copy_tasks
echo Копируем папку задач...
if exist "%PROJECT_DIR%\orcestrator\tasks" (
    mkdir "%TEMP_BACKUP%\orcestrator"
    xcopy /E /I /Y /Q "%PROJECT_DIR%\orcestrator\tasks" "%TEMP_BACKUP%\orcestrator\tasks" >nul
)
goto remove_old

:skip_tasks
echo Папка задач не сохраняется, будут загружены задачи из GitHub.
goto remove_old

:remove_old
echo Удаляем старую папку проекта...
rmdir /S /Q "%PROJECT_DIR%"
if exist "%PROJECT_DIR%" (
    echo [ОШИБКА] Не удалось удалить папку. Возможно, она открыта в проводнике.
    pause
    exit /b 1
)

:no_old_project
echo Устанавливаем новую версию...
ren "Python_VS_Sport-main" "%PROJECT_DIR%"

if not exist "%TEMP_BACKUP%" goto update_done

echo Восстанавливаем сохраненные файлы...
if exist "%TEMP_BACKUP%\web\contest_web.db" (
    copy /Y "%TEMP_BACKUP%\web\contest_web.db" "%PROJECT_DIR%\web\contest_web.db" >nul
)

if exist "%TEMP_BACKUP%\.env" (
    copy /Y "%TEMP_BACKUP%\.env" "%PROJECT_DIR%\.env" >nul
)

if exist "%TEMP_BACKUP%\orcestrator\tasks" (
    xcopy /E /I /Y /Q "%TEMP_BACKUP%\orcestrator\tasks" "%PROJECT_DIR%\orcestrator\tasks" >nul
)

rmdir /S /Q "%TEMP_BACKUP%"

:update_done
echo OK: Обновление завершено.

cd /d "%PROJECT_DIR%"

echo.
echo [4/5] Проверка окружения .venv
if exist ".venv\Scripts\python.exe" goto venv_ok

echo Создаем новое окружение .venv, пожалуйста подождите...
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
if not exist "requirements.txt" (
    echo [ОШИБКА] Файл requirements.txt не найден!
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
".venv\Scripts\python.exe" -m pip install -r requirements.txt --only-binary=:all:
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
)
echo OK: Зависимости установлены.

if exist ".env" goto skip_env
if not exist ".env.example" goto skip_env
copy /Y ".env.example" ".env" >nul
echo OK: .env создан.

:skip_env
echo.
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
echo   Установка завершена! Запускаем сервер с правами администратора...

:: Запускаем наш стартер, который запросит права админа
start "" "start_server.bat"

echo.
echo Установка полностью завершена. Это окно можно закрыть.
timeout /t 3 >nul
exit /b 0
