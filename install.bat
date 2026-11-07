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

REM --- БЭКАП БАЗЫ И НАСТРОЕК ---
if exist "%PROJECT_DIR%\web\contest_web.db" (
    echo Сохраняем текущую базу данных...
    if not exist "%TEMP%\sport_backup" mkdir "%TEMP%\sport_backup"
    copy /Y "%PROJECT_DIR%\web\contest_web.db" "%TEMP%\sport_backup\contest_web.db" >nul
)
if exist "%PROJECT_DIR%\.env" (
    echo Сохраняем файл настроек .env...
    if not exist "%TEMP%\sport_backup" mkdir "%TEMP%\sport_backup"
    copy /Y "%PROJECT_DIR%\.env" "%TEMP%\sport_backup\.env" >nul
)

REM --- УДАЛЕНИЕ СТАРОЙ ПАПКИ ---
if exist "%PROJECT_DIR%" (
    echo Удаляем старую папку проекта...
    rmdir /S /Q "%PROJECT_DIR%"
)

REM --- СКАЧИВАНИЕ И РАСПАКОВКА ---
set "ZIP_FILE=%TEMP%\project.zip"
echo Скачиваем архив...
curl -L -o "%ZIP_FILE%" "%ZIP_URL%"
if not exist "%ZIP_FILE%" (
    echo [ОШИБКА] Не удалось скачать архив. Проверьте интернет.
    pause
    exit /b 1
)

echo Распаковываем архив...
tar -xf "%ZIP_FILE%" -C "%CD%"

if not exist "Python_VS_Sport-main" (
    echo [ОШИБКА] Архив распаковался, но папка Python_VS_Sport-main не найдена.
    pause
    exit /b 1
)

ren "Python_VS_Sport-main" "%PROJECT_DIR%"
del /q "%ZIP_FILE%"
echo OK: Файлы успешно скопированы.

REM --- ВОССТАНОВЛЕНИЕ БАЗЫ И НАСТРОЕК ---
if exist "%TEMP%\sport_backup\contest_web.db" (
    copy /Y "%TEMP%\sport_backup\contest_web.db" "%PROJECT_DIR%\web\contest_web.db" >nul
    echo OK: База данных восстановлена.
)
if exist "%TEMP%\sport_backup\.env" (
    copy /Y "%TEMP%\sport_backup\.env" "%PROJECT_DIR%\.env" >nul
    echo OK: Файл .env восстановлен.
)
if exist "%TEMP%\sport_backup" rmdir /S /Q "%TEMP%\sport_backup"

cd /d "%PROJECT_DIR%"

echo.
echo [3/5] Проверка зависимостей и создание .venv
if exist ".venv" rmdir /S /Q ".venv"

echo Создаем чистое окружение .venv...
"%PYTHON_EXE%" -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Не удалось создать .venv.
    pause
    exit /b 1
)
echo OK: .venv создано.

echo.
echo [4/5] Установка библиотек
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
echo OK: Библиотеки установлены.

echo.
echo [5/5] Запуск сервера
echo.
echo Сервер запускается, браузер откроется автоматически...

cd web
start "Python vs Sport Server" cmd /k "..\.venv\Scripts\python.exe run.py"
cd ..
cd ..

echo.
echo Установка завершена. Нажмите любую клавишу для выхода.
pause
exit /b 0
