from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
from app.config import settings

ALGORITHM = "HS256"
MAX_PASSWORD_BYTES = 72


def _to_bytes(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raw = raw[:MAX_PASSWORD_BYTES]
    return raw


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain_password), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    # PyJWT требует, чтобы "sub" был строкой
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])

    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError as e:
        print(f"DEBUG JWT ERROR: {e}")
        return None