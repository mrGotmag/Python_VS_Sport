import secrets
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # Корень проекта
env_path = BASE_DIR / ".env"

# Если файла .env вообще нет, создаем его с базовыми настройками
if not env_path.exists():
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("DATABASE_URL=sqlite:///./contest_web.db\n")
        f.write("PORT=8000\n")
        f.write("HOST=0.0.0.0\n")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(env_path),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    app_name: str = "Python vs Спорт"

    # ДОБАВЛЕНО = "": чтобы pydantic не падал, если ключа нет
    secret_key: str = ""

    access_token_expire_minutes: int = 480
    team_size: int = 5
    max_phases_per_team: int = 9

    database_url: str = "sqlite:///./contest_web.db"
    port: int = 8000
    host: str = "0.0.0.0"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"


# 1. Загружаем настройки
settings = Settings()

# 2. Проверяем, есть ли ключ. Если пустой или короткий (из .env.example) — генерируем
if not settings.secret_key or len(settings.secret_key) < 10:
    new_key = secrets.token_urlsafe(64)
    settings.secret_key = new_key

    # Безопасно перезаписываем .env, чтобы не было дублей SECRET_KEY=
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # Удаляем старые строки с SECRET_KEY
    lines = [line for line in lines if not line.strip().startswith("SECRET_KEY=")]
    # Добавляем новый
    lines.append(f"SECRET_KEY={new_key}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)