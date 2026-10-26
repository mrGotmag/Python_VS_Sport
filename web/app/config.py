from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Разрешаем лишние переменные из .env (чтобы не было ошибки Extra inputs)
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    app_name: str = "Python vs Спорт"
    secret_key: str = "super-secret-key-change-me"
    access_token_expire_minutes: int = 480

    # Добавляем переменные, которые есть в .env
    database_url: str = "sqlite:///./contest_web.db"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"


settings = Settings()