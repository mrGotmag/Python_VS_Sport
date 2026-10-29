from datetime import datetime
from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey, Text, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class GlobalSettings(Base):
    __tablename__ = "global_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    is_started: Mapped[bool] = mapped_column(Boolean, default=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)

    # Индекс текущей фазы (0 = первая фаза)
    current_phase_index: Mapped[int] = mapped_column(Integer, default=0)
    phase_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Phase(Base):
    """Фаза соревнования: либо задача, либо спортивное упражнение."""
    __tablename__ = "phases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    # Тип: "task" (программирование) или "sport" (перерыв/физкультура)
    type: Mapped[str] = mapped_column(String(32), default="task")

    # Для задач: ID задачи из папки tasks/{id}
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Для спорта: название упражнения
    sport_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Время на фазу в секундах (30 мин = 1800, 10 мин = 600)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=1800)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    school: Mapped[str | None] = mapped_column(String(128), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(64), nullable=True)
    leader_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    leader_email: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Таймеры команды
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Индивидуальный прогресс по фазам
    current_phase_index: Mapped[int] = mapped_column(Integer, default=0)
    phase_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(255))
    statement: Mapped[str] = mapped_column(Text)
    points_max: Mapped[int] = mapped_column(Integer, default=10)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")

    # Баллы за тесты
    score: Mapped[int] = mapped_column(Integer, default=0)

    # Для тай-брейка
    time_ms: Mapped[float] = mapped_column(Float, default=0.0)  # Время в миллисекундах
    memory_mb: Mapped[float] = mapped_column(Float, default=0.0)  # Пиковая память в МБ

    time_spent: Mapped[int] = mapped_column(Integer, default=0)  # Общее время от старта олимпиады
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SportResult(Base):
    """Ручные баллы за спортивные упражнения."""
    __tablename__ = "sport_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))

    # Привязка к фазе (чтобы видеть, за какое именно упражнение балл)
    phase_id: Mapped[int | None] = mapped_column(ForeignKey("phases.id"), nullable=True)
    exercise_name: Mapped[str] = mapped_column(String(128))
    points: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)