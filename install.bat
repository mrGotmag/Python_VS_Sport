@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM --- Проверка прав Администратора (для брандмауэра) ---
net session >nul 2>&1
if errorlevel 1 (
    echo [ПРЕДУПРЕЖДЕНИЕ] Вы запустили установщик без прав Администратора.
    echo Брандмауэр Windows может заблокировать доступ участников к сайту.
    echo Рекомендуется закрыть это окно и запустить install.bat от имени Администратора.
    echo.
    pause
)

cd /d "%USERPROFILE%\Desktop"
echo [ИНФО] Мы находимся в папке: %CD%

set "PROJECT_DIR=Python_VS_Sport"
set "ZIP_URL=https://github.com/mrGotmag/Python_VS_Sport/archive/refs/heads/main.zip"

echo.
echo ============================================================
echo   Установка проекта Python vs Sport
echo ============================================================
echo.

REM ---- 1) Проверка Python 3.12 ----
echo [1/5] Проверка Python 3.12...
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"

if exist "%PYTHON_EXE%" (
    echo   Python 3.12 уже установлен.
    goto :python_ok
)

echo   Python 3.12 не найден. Скачиваем...
set "PY_INSTALLER=%TEMP%\python_install.exe"
curl -L -o "%PY_INSTALLER%" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

if not exist "%PY_INSTALLER%" (
    echo ОШИБКА: Не удалось скачать установщик Python.
    pause
    exit /b 1
)

echo   Устанавливаем Python 3.12 (займет пару минут)...
start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 Include_launcher=1
del /q "%PY_INSTALLER%"

echo   Ждем 3 секунды...
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
echo [2/5] Скачивание файлов с GitHub...

if exist "%PROJECT_DIR%" (
    echo   Удаляем старую папку...
    rmdir /S /Q "%PROJECT_DIR%"
)

set "ZIP_FILE=%TEMP%\project.zip"
echo   Скачиваем архив (пожалуйста, подождите)...
curl -L -o "%ZIP_FILE%" "%ZIP_URL%"

if not exist "%ZIP_FILE%" (
    echo [ОШИБКА] Не удалось скачать архив. Проверьте интернет.
    pause
    exit /b 1
)

echo   Распаковываем через PowerShell...
REM Используем PowerShell для распаковки, так как он работает 100% стабильно на всех Windows
powershell -command "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%CD%' -Force"

REM Переименовываем папку (GitHub добавляет -main к имени)
if exist "Python_VS_Sport-main" (
    ren "Python_VS_Sport-main" "%PROJECT_DIR%"
) else (
    echo [ОШИБКА] Архив скачался, но папка Python_VS_Sport-main не найдена!
    echo Возможно, вы поменяли название ветки на GitHub (вместо main используется master).
    pause
    exit /b 1
)

del /q "%ZIP_FILE%"
echo   OK: файлы готовы. Они лежат в: %CD%\%PROJECT_DIR%

cd "%PROJECT_DIR%"

REM ---- 3) Создание venv ----
echo.
echo [3/5] Проверка .venv...

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

REM ---- 4) Установка зависимостей ----
echo.
echo [4/5] Установка зависимостей (займет 1-2 минуты)...
if exist "requirements.txt" (
    ".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel >nul
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

REM ---- 5) Подготовка .env ----
echo.
echo [5/5] Подготовка .env...
if exist ".env" (
    echo   .env существует.
) else if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo   OK: .env создан.
)

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
echo   Запускаем сервер (браузер откроется автоматически)...

cd web
start "Python vs Sport Server" cmd /k "..\.venv\Scripts\python.exe run.py"
cd ..

cd ..
echo.
echo Установка завершена. Нажмите любую клавишу, чтобы закрыть это окно.
pause
exit /b 0