import uvicorn
import socket
import webbrowser
import threading
import subprocess
import sys


def get_real_local_ips():
    """Ищет только реальные IP-адреса для локальной сети, отбрасывая виртуальные."""
    ips = []
    try:
        # Способ 1: Узнаем IP через подключение к внешнему серверу (самый надежный)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        main_ip = s.getsockname()[0]
        s.close()
        if main_ip and main_ip != "127.0.0.1":
            ips.append(main_ip)
    except Exception:
        pass

    # Способ 2: Смотрим все интерфейсы
    try:
        hostname = socket.gethostname()
        all_ips = socket.gethostbyname_ex(hostname)[2]
        for ip in all_ips:
            if ip in ips or ip.startswith("127."):
                continue
            # Фильтруем виртуальные сети (VirtualBox, VMware, Docker)
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
    PORT = 8000

    print("=" * 60)
    print(" ЗАПУСК СЕРВЕРА PYTHON VS SPORT")
    print("=" * 60)

    open_firewall_port(PORT)

    # Получаем отфильтрованные адреса
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
        uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=True)
    except KeyboardInterrupt:
        print("\nСервер остановлен.")