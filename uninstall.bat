@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: --- Проверка: запущен ли скрипт изнутри проекта? ---
if exist "%~dp0web\run.py" (
    echo [ИНФО] Скрипт запущен изнутри папки проекта.
    echo [ИНФО] Копируем скрипт во временную папку Windows для удаления...
    
    :: Запоминаем путь к проекту (убираем слэш в конце, если есть)
    set "PROJ_PATH=%~dp0"
    if "!PROJ_PATH:~-1!"=="\" set "PROJ_PATH=!PROJ_PATH:~0,-1!"
    
    :: Копируем этот скрипт в TEMP
    copy /Y "%~f0" "%TEMP%\uninstall_temp.bat" >nul
    
    :: Запускаем копию, передавая ей путь к проекту
    call "%TEMP%\uninstall_temp.bat" "!PROJ_PATH!"
    exit /b
)

:: --- Мы запущены из временной папки TEMP ---
title Удаление Python vs Sport

:: Получаем путь к проекту из аргумента
set "TARGET_DIR=%~1"
if "%TARGET_DIR%"=="" set "TARGET_DIR=%~dp0Python_VS_Sport"

:: --- Проверка прав Администратора ---
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ============================================================
    echo   ТРЕБУЮТСЯ ПРАВА АДМИНИСТРАТОРА
    echo ============================================================
    echo   Сейчас появится окно запроса прав. Нажмите "Да".
    echo.
    :: Перезапускаем эту же копию из TEMP, но с правами админа
    powershell -Command "Start-Process -FilePath '%~f0' -ArgumentList '%TARGET_DIR%' -Verb RunAs"
    exit /b
)

echo ============================================================
echo   УДАЛЕНИЕ ПРОЕКТА PYTHON VS SPORT
echo ============================================================
echo.
echo ВНИМАНИЕ: Это действие полностью удалит папку:
echo %TARGET_DIR%
echo Вся база данных и задачи будут УДАЛЕНЫ безвозвратно!
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
if exist "%TARGET_DIR%" (
    rmdir /S /Q "%TARGET_DIR%"
    echo   OK: Папка проекта удалена.
) else (
    echo   [ИНФО] Папка проекта не найдена (возможно, уже удалена).
)

:: Удаляем временный файл скрипта
if exist "%TEMP%\uninstall_temp.bat" del /q "%TEMP%\uninstall_temp.bat"

echo.
echo ============================================================
echo   УДАЛЕНИЕ ЗАВЕРШЕНО УСПЕШНО
echo ============================================================
pause
exit /b 0

:cancel
echo.
echo Удаление отменено пользователем.
if exist "%TEMP%\uninstall_temp.bat" del /q "%TEMP%\uninstall_temp.bat"
pause
exit /b 0
