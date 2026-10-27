import secrets
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent # Корень проекта
env_path = BASE_DIR / ".env"

# Проверяем и создаем .env с секретным ключом, если его нет
if not env_path.exists() or "SECRET_KEY=" not in env_path.read_text(encoding="utf-8"):
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"\nSECRET_KEY={secrets.token_urlsafe(64)}\n")
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
    secret_key: str
    access_token_expire_minutes: int = 480

    database_url: str = "sqlite:///./contest_web.db"
    port: int = 8000
    host: str = "0.0.0.0"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

settings = Settings()