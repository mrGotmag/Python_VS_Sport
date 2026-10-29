import uvicorn
import socket
import webbrowser
import threading
import subprocess
import sys
import os
from pathlib import Path

# Загружаем .env вручную, чтобы получить PORT и HOST до старта FastAPI
try:
    from dotenv import load_dotenv
    # Ищем .env в корне проекта (на два уровня выше папки web)
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    print("[ПРЕДУПРЕЖДЕНИЕ] python-dotenv не установлен. Используются настройки по умолчанию.")

PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

def get_real_local_ips():
    """Ищет только реальные IP-адреса для локальной сети, отбрасывая виртуальные."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        main_ip = s.getsockname()[0]
        s.close()
        if main_ip and main_ip != "127.0.0.1":
            ips.append(main_ip)
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        all_ips = socket.gethostbyname_ex(hostname)[2]
        for ip in all_ips:
            if ip in ips or ip.startswith("127."):
                continue
            if ip.startswith("192.168.56.") or ip.startswith("172.17."):
                continue
            ips.append(ip)
    except Exception:
        pass

    return ips

def open_firewall_port(port):
    """Добавляет правило в брандмауэр Windows."""
    if sys.platform != "win32":
        return False

    check_cmd = f'netsh advfirewall firewall show rule name="Python vs Sport {port}"'
    result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)

    if "No rules match" in result.stdout or "Нет правил" in result.stdout or result.returncode != 0:
        print(f"[СЕТЬ] Пробуем открыть порт {port} в брандмауэре...")
        add_cmd = f'netsh advfirewall firewall add rule name="Python vs Sport {port}" dir=in action=allow protocol=TCP localport={port}'
        res = subprocess.run(add_cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"[СЕТЬ] Порт {port} успешно открыт!")
            return True
        else:
            print(f"[СЕТЬ] Не удалось открыть порт. Запустите от имени администратора.")
            return False
    return True

if __name__ == "__main__":
    print("=" * 60)
    print(" ЗАПУСК СЕРВЕРА PYTHON VS SPORT")
    print("=" * 60)

    open_firewall_port(PORT)
    ips = get_real_local_ips()

    print("\n[ИНФО] Сервер успешно запущен!")
    print(f"[ИНФО] Локально на этом ПК: http://localhost:{PORT}")

    if ips:
        print("\n[ИНФО] Попробуйте подключиться с других устройств по одному из этих адресов:")
        for ip in ips:
            print(f"       -> http://{ip}:{PORT}")
    else:
        print("\n[ВНИМАНИЕ] Не удалось определить IP вашей локальной сети. Проверьте подключение к Wi-Fi/кабелю.")

    print("\n[СОВЕТ] Устройства должны быть в ОДНОЙ сети (Wi-Fi или роутере).")
    print("[СОВЕТ] Если не работает, убедитесь, что вы запускаете install.bat от имени Администратора.")

    print("\nОткрываем браузер на этом ПК...")
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    print("-" * 60)
    print("Сервер работает. Для остановки нажмите Ctrl+C.")
    print("-" * 60 + "\n")

    try:
        # Запускаем uvicorn с настройками из .env
        uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
    except KeyboardInterrupt:
        print("\nСервер остановлен.")