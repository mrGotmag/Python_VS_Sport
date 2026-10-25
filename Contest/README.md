# Orchestrator — проверка олимпиадных задач

## Установка (Windows)

1. Скачайте `install.bat` из этого репозитория.
2. Поменяйте в нём `REPO_URL` на URL этого репозитория.
3. Запустите `install.bat`.

## Установка (Linux/macOS)

```bash
git clone <URL> orchestrator
cd orchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py tasks --only 1
```

## Использование

```bash
python main.py tasks              # все задачи
python main.py tasks --only 1     # только задача 1
python main.py tasks --workers 4  # 4 воркера
```