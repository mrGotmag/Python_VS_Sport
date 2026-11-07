@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: --- Проверка: запущен ли скрипт изнутри проекта? ---
if exist "%~dp0web\run.py" if exist "%~dp0orcestrator" (
    echo [ИНФО] Скрипт запущен изнутри папки проекта.
    echo [ИНФО] Перемещаем удаление в родительскую папку, чтобы Windows разблокировал файлы...

    :: Получаем путь к родительской папке и имя текущей папки
    for %%A in ("%~dp0..") do set "PARENT_DIR=%%~fA"
    for %%A in ("%~dp0.") do set "PROJECT_FOLDER=%%~nxA"

    :: Копируем этот скрипт в родительскую папку
    copy "%~f0" "%PARENT_DIR%\uninstall_temp.bat" >nul

    :: Запускаем копию из родительской папки, передавая имя проекта как аргумент
    cd /d "%PARENT_DIR%"
    start "" cmd /c "uninstall_temp.bat" "%PROJECT_FOLDER%"
    exit /b
)

:: --- Мы запущены извне ---
title Удаление Python vs Sport

:: Если имя проекта передано аргументом (из первого блока), используем его
set "PROJECT_DIR=Python_VS_Sport"
if not "%~1"=="" set "PROJECT_DIR=%~1"

:: --- Проверка прав Администратора ---
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ============================================================
    echo   ТРЕБУЮТСЯ ПРАВА АДМИНИСТРАТОРА
    echo ============================================================
    echo   Для удаления правила брандмауэра нужны права админа.
    echo   Сейчас появится окно запроса прав. Нажмите "Да".
    echo.
    powershell -Command "Start-Process -FilePath '%~f0' -ArgumentList '%PROJECT_DIR%' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================================
echo   УДАЛЕНИЕ ПРОЕКТА PYTHON VS SPORT
echo ============================================================
echo.
echo ВНИМАНИЕ: Это действие полностью удалит папку "%PROJECT_DIR%".
echo Вся база данных (результаты) и задачи будут УДАЛЕНЫ безвозвратно!
echo.

choice /C YN /M "Вы уверены, что хотите удалить проект"
if errorlevel 2 goto cancel
if errorlevel 1 goto uninstall

:uninstall
echo.
echo [1/3] Останавливаем работающие процессы Python...
taskkill /F /IM python.exe /T >nul 2>&1
echo   OK: Процессы остановлены.

echo [2/3] Удаляем правило брандмауэра...
netsh advfirewall firewall delete rule name="Python vs Sport 8000" >nul 2>&1
echo   OK: Правило удалено.

echo [3/3] Удаляем папку проекта...
if exist "%PROJECT_DIR%" (
    rmdir /S /Q "%PROJECT_DIR%"
    echo   OK: Папка %PROJECT_DIR% удалена.
) else (
    echo   [ИНФО] Папка %PROJECT_DIR% не найдена.
)

:: Удаляем временный файл, если он был создан
if exist "%~dp0uninstall_temp.bat" del /q "%~dp0uninstall_temp.bat"

echo.
echo ============================================================
echo   УДАЛЕНИЕ ЗАВЕРШЕНО УСПЕШНО
echo ============================================================
pause
exit /b 0

:cancel
echo.
echo Удаление отменено пользователем.
if exist "%~dp0uninstall_temp.bat" del /q "%~dp0uninstall_temp.bat"
pause
exit /b 0