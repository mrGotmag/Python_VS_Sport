import secrets
import subprocess
import sys
import re
import json
import shutil
import markdown
import csv
import io
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
import threading
from typing import List

from app.config import settings
# Импортируем все модели
from app.models import Base, AdminUser, GlobalSettings, Organization, Team, Task, Submission, Phase, SportResult, Participant, Judge
from app.security import get_password_hash, verify_password, create_access_token, decode_token
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from datetime import datetime, timedelta, timezone

register_lock = threading.Lock()
# Единый источник правды для путей — orcestrator/config.py
import sys as _sys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # = Contest/
_orch_path = str(_PROJECT_ROOT / "orcestrator")
if _orch_path not in _sys.path:
    _sys.path.insert(0, _orch_path)

from config import settings as _orch_settings  # orcestrator/config.py

ORCESTRATOR_DIR = _PROJECT_ROOT / "orcestrator"
TASKS_DIR = _orch_settings.tasks_dir

connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}
engine = create_engine(settings.database_url, connect_args=connect_args)

from sqlalchemy import event

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name)

def utc_now():
    """Возвращает текущее время UTC без таймзоны (для совместимости с SQLite)"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

templates = Jinja2Templates(directory="app/templates")


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        # Используем копию списка, чтобы безопасно удалять элементы во время итерации
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection) # <--- Удаляем, если связь потеряна


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, ConnectionResetError): # <--- Ловим обрыв связи Windows
        manager.disconnect(websocket)


def sync_tasks_from_disk():
    with Session(engine) as db:
        if not TASKS_DIR.exists():
            print(f"[WARN] Папка {TASKS_DIR} не существует!")
            return

        valid_ids = [int(f.name) for f in TASKS_DIR.iterdir() if f.is_dir() and f.name.isdigit()]
        valid_ids.sort()
        # print(f"[SYNC] Найдено папок с задачами: {len(valid_ids)}")

        # 1. Обновляем задачи в БД
        for et in db.query(Task).all():
            if et.id not in valid_ids:
                db.query(Submission).filter_by(task_id=et.id).delete() # <--- ДОБАВИТЬ
                db.delete(et)
        db.commit()

        for tid in valid_ids:
            f = TASKS_DIR / str(tid) / "task.txt"
            if not f.exists(): continue
            raw = f.read_text(encoding="utf-8").strip()
            title = re.sub(r'^Задача\s*\d+[-.:]?\s*', '', raw.split('\n')[0], flags=re.IGNORECASE).strip()

            tests = TASKS_DIR / str(tid) / "tests.json"
            pts = 10
            if tests.exists():
                try:
                    pts = sum(
                        t.get("points", 0) for t in json.loads(tests.read_text(encoding="utf-8")).get("tests", []))
                except:
                    pass

            et = db.query(Task).filter(Task.id == tid).first()
            if not et:
                db.add(Task(id=tid, order_index=tid, title=title, statement="", points_max=pts))
            else:
                et.title, et.points_max = title, pts
        db.commit()

        # 2. АВТОМАТИЧЕСКАЯ СБОРКА ФАЗ
        current_phases = db.query(Phase).order_by(Phase.order_index).all()

        # Генерируем фазы ТОЛЬКО если список фаз полностью пуст (первый запуск)
        if len(current_phases) == 0 and valid_ids:
            print(f"[SYNC] Первичная генерация фаз для {len(valid_ids)} задач...")

            for idx, tid in enumerate(valid_ids):
                # Добавляем фазу с задачей
                db.add(Phase(
                    order_index=len(db.query(Phase).all()),
                    type="task",
                    task_id=tid,
                    duration_seconds=1800  # 30 мин по умолчанию
                ))
                db.commit()

                # Если это не последняя задача, добавляем фазу со спортом
                if idx < len(valid_ids) - 1:
                    db.add(Phase(
                        order_index=len(db.query(Phase).all()),
                        type="sport",
                        sport_name=f"Спорт {tid}",
                        duration_seconds=600  # 10 мин по умолчанию
                    ))
                    db.commit()

            print(f"[SYNC] Автоматически создано {len(db.query(Phase).all())} фаз.")


def cleanup_temp_folders():
    if not TASKS_DIR.exists(): return
    count = 0
    for task_dir in TASKS_DIR.iterdir():
        if task_dir.is_dir() and (task_dir / "temp").exists():
            try:
                shutil.rmtree(task_dir / "temp")
                count += 1
            except Exception as e:
                print(f"[WARN] Не удалось очистить {task_dir}/temp: {e}")
    if count > 0:
        print(f"[CLEANUP] Очищено {count} временных папок от старых проверок.")


sync_tasks_from_disk()
cleanup_temp_folders()

# Инициализация настроек
with Session(engine) as db:
    if not db.query(GlobalSettings).first():
        db.add(GlobalSettings(id=1, is_started=False, is_paused=False))
        db.commit()


def get_current_team(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token: raise HTTPException(401, "Нет токена")
    payload = decode_token(token)
    if not payload or payload.get("role") != "team": raise HTTPException(401, "Неверный токен")
    team = db.get(Team, int(payload.get("sub")))
    if not team or not team.is_active: raise HTTPException(401, "Команда недоступна")
    return team


def get_current_participant(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token: return None
    payload = decode_token(token)
    if not payload: return None
    pid = payload.get("participant_id")
    if pid:
        return db.get(Participant, int(pid))
    return None


def get_current_admin(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token: raise HTTPException(401, "Нет токена")
    payload = decode_token(token)
    if not payload or payload.get("role") != "admin": raise HTTPException(403, "Нужен токен админа")
    return db.get(AdminUser, int(payload.get("sub")))


def get_current_judge(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token: raise HTTPException(401, "Нет токена")
    payload = decode_token(token)
    if not payload or payload.get("role") != "judge": raise HTTPException(403, "Нужен токен судьи")
    return db.get(Judge, int(payload.get("sub")))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    with Session(engine) as db:
        if not db.query(AdminUser).first(): return RedirectResponse("/setup")
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    with Session(engine) as db:
        if db.query(AdminUser).first(): return RedirectResponse("/")
    return templates.TemplateResponse("setup.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/team", response_class=HTMLResponse)
async def team_page(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/")

    payload = decode_token(token)
    if not payload or payload.get("role") != "team":
        return RedirectResponse("/")

    return templates.TemplateResponse("team.html", {"request": request})


@app.get("/results", response_class=HTMLResponse)
async def results_page(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/")

    payload = decode_token(token)
    if not payload or payload.get("role") != "team":
        return RedirectResponse("/")

    # Проверяем: команда реально финишировала?
    with Session(engine) as db:
        team = db.get(Team, int(payload.get("sub")))
        if not team:
            return RedirectResponse("/")
        if team.finished_at is None:
            # ещё не финишировала — обратно в кабинет
            return RedirectResponse("/team")

    return templates.TemplateResponse("results.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/")

    payload = decode_token(token)
    if not payload or payload.get("role") != "admin":
        return RedirectResponse("/")

    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/logout")
async def logout():
    res = RedirectResponse("/")
    res.delete_cookie("access_token")
    return res


@app.post("/api/setup")
async def setup_admin(request: Request):
    form = await request.form()
    pwd = (form.get("password") or "").strip()
    if len(pwd) < 5: raise HTTPException(400, "Пароль слишком короткий")
    with Session(engine) as db:
        if db.query(AdminUser).first(): raise HTTPException(400, "Админ уже создан")
        db.add(AdminUser(password_hash=get_password_hash(pwd)))
        db.commit()
    return JSONResponse({"status": "ok"})


@app.post("/api/login")
async def login(request: Request):
    form = await request.form()
    pwd = (form.get("password") or "").strip()
    with Session(engine) as db:
        admin = db.query(AdminUser).first()
        if admin and verify_password(pwd, admin.password_hash):
            token = create_access_token({"sub": admin.id, "role": "admin"})
            res = JSONResponse({"status": "ok", "role": "admin"})
            res.set_cookie("access_token", token, httponly=True)
            return res

        # Проверка судьи
        matched_judge = next((j for j in db.query(Judge).all() if verify_password(pwd, j.password_hash)), None)
        if matched_judge:
            token = create_access_token({"sub": matched_judge.id, "role": "judge"})
            res = JSONResponse({"status": "ok", "role": "judge"})
            res.set_cookie("access_token", token, httponly=True)
            return res

        # Проверка входа участника по персональному коду
        participant = db.query(Participant).filter(Participant.login_code == pwd).first()
        if participant:
            team = db.get(Team, participant.team_id)
            if not team or not team.is_active:
                raise HTTPException(401, "Команда недоступна")
            # ДОБАВЛЯЕМ participant_id В ТОКЕН:
            token = create_access_token({"sub": team.id, "participant_id": participant.id, "role": "team"})
            res = JSONResponse({"status": "ok", "role": "team"})
            res.set_cookie("access_token", token, httponly=True)
            return res

        matched_org = next((o for o in db.query(Organization).all() if verify_password(pwd, o.password_hash)), None)
        if not matched_org: raise HTTPException(401, "Неверный пароль")

        team = db.query(Team).filter(Team.organization_id == matched_org.id).first()
        if not team:
            team = Team(name=f"Команда {matched_org.name}", organization_id=matched_org.id)
            db.add(team)
            db.commit()
            db.refresh(team)

        token = create_access_token({"sub": team.id, "role": "team"})
        res = JSONResponse({"status": "ok", "role": "team"})
        res.set_cookie("access_token", token, httponly=True)
        return res


@app.get("/api/team/me")
async def get_me(request: Request):
    with Session(engine) as db:
        team = get_current_team(request, db)
        gs = db.query(GlobalSettings).first()
        phases = db.query(Phase).order_by(Phase.order_index).all()

        # Если команда зашла впервые, запускаем её личный таймер
        if team.started_at is None and gs.is_started:
            # Ждём полной посадки, если админ не запустил принудительно
            if not team.is_full and not team.force_started:
                return {
                    "team": {
                        "name": team.name,
                        "is_paused": False,
                        "finished_at": None,
                        "finished_by_phases": False,
                        "total_time_seconds": 0,
                        "waiting_for_team": True,
                        "team_size": db.query(Participant).filter(Participant.team_id == team.id).count(),
                        "team_max": settings.team_size,
                    },
                    "global": {"is_started": gs.is_started, "is_paused": gs.is_paused, "current_phase_index": 0,
                               "total_phases": len(phases), "phase_type": "none", "phase_task_id": None,
                               "phase_sport_name": None, "phase_time_left": 0, "is_break": False},
                    "contest": {"remaining_seconds": 0},
                    "tasks": []
                }

            # Запускаем таймер ТОЛЬКО СЕЙЧАС
            team.started_at = utc_now()
            team.phase_started_at = utc_now()
            db.commit()

        current_phase = None
        time_left = 0
        is_break = False

        # Признак, что команда прошла все фазы (последняя + время вышло)
        is_finished_by_phases = False

        if gs.is_started and phases:
            # Проверяем, не вышло ли время текущей фазы у команды
            if team.current_phase_index < len(phases):
                current_phase = phases[int(team.current_phase_index)]  # type: ignore

                if team.phase_started_at:
                    elapsed = (utc_now() - team.phase_started_at).total_seconds()
                    time_left = max(0, int(current_phase.duration_seconds - elapsed))

                    # Если время вышло, переключаем на следующую фазу
                    if time_left == 0:
                        # Определяем лимит: если у команды есть свой лимит (админ менял), берем его. Иначе - глобальный.
                        current_limit = team.phase_limit if team.phase_limit > 0 else settings.max_phases_per_team

                        if team.current_phase_index < len(phases) - 1 and (
                                team.current_phase_index + 1) < current_limit:
                            team.current_phase_index += 1
                            team.phase_started_at = utc_now()
                            db.commit()
                            # Перечитываем данные для новой фазы
                            current_phase = phases[int(team.current_phase_index)]  # type: ignore
                            time_left = current_phase.duration_seconds
                        else:
                            # Достигли лимита фаз ИЛИ это была последняя фаза — команда завершила
                            if team.finished_at is None:
                                team.finished_at = utc_now()
                                db.commit()
                            is_finished_by_phases = True

                is_break = current_phase.type == "sport"

        # Считаем общее время в олимпиаде
        total_time = 0
        if team.started_at:
            total_time = int((utc_now() - team.started_at).total_seconds())

        tasks = db.execute(select(Task).where(Task.is_active == True).order_by(Task.order_index)).scalars().all()
        tasks_out = []
        participant = get_current_participant(request, db)
        for t in tasks:
            # Ищем лучшую посылку КОНКРЕТНОГО УЧАСТНИКА
            best_sub = None
            if participant:
                best_sub = db.query(Submission).filter_by(
                    participant_id=participant.id, task_id=t.id
                ).order_by(Submission.score.desc()).first()

            tasks_out.append({
                "id": t.id, "title": t.title, "order_index": t.order_index, "max_points": t.points_max,
                "current_score": best_sub.score if best_sub else 0,
                "time_spent": best_sub.time_spent if best_sub else 0
            })

        return {
            "team": {
                "name": team.name,
                "is_paused": team.is_paused,
                "finished_at": team.finished_at.isoformat() if team.finished_at else None,
                "finished_by_phases": is_finished_by_phases,
                "total_time_seconds": total_time,
            },
            "global": {
                "is_started": gs.is_started,
                "is_paused": gs.is_paused,
                "current_phase_index": team.current_phase_index,
                "total_phases": len(phases),
                "phase_type": current_phase.type if current_phase else "none",
                "phase_task_id": current_phase.task_id if current_phase else None,
                "phase_sport_name": current_phase.sport_name if current_phase else None,
                "phase_time_left": time_left,
                "is_break": is_break
            },
            "contest": {"remaining_seconds": 0},
            "tasks": tasks_out
        }


@app.get("/api/team/leaderboard")
async def get_leaderboard(request: Request):
    with Session(engine) as db:
        get_current_team(request, db)
        participant_current = get_current_participant(request, db)
        participants = db.query(Participant).all()
        teams = {t.id: t.name for t in db.query(Team).all()}

        rows = []
        for p in participants:
            subs = db.query(Submission).filter_by(participant_id=p.id).all()
            best_scores = {}
            for s in subs:
                cur = best_scores.get(s.task_id)
                if cur is None:
                    best_scores[s.task_id] = s
                    continue
                s_key = (s.score or 0, -(s.time_ms or 0), -(s.memory_mb or 0))
                c_key = (cur.score or 0, -(cur.time_ms or 0), -(cur.memory_mb or 0))
                if s_key > c_key:
                    best_scores[s.task_id] = s

            code_score = sum((s.score or 0) for s in best_scores.values())
            rows.append({
                "id": p.id, "name": p.name,
                "team_name": teams.get(p.team_id, "—"),
                "code_score": code_score, "total_score": code_score,
                "is_me": p.id == participant_current.id if participant_current else False
            })

        rows.sort(key=lambda r: -r["total_score"])
        current_place = 1
        for i, r in enumerate(rows):
            if i > 0 and rows[i-1]["total_score"] != r["total_score"]:
                current_place = i + 1
            r["place"] = current_place

        my_place = next((r["place"] for r in rows if r["is_me"]), None)
        return {"teams": rows, "my_place": my_place}


@app.get("/api/team/tasks/{task_id}")
async def get_task_detail(task_id: int, request: Request):
    with Session(engine) as db:
        team = get_current_team(request, db)
        phases = db.query(Phase).order_by(Phase.order_index).all()

        # Проверка: это текущая задача?
        current_phase = phases[int(team.current_phase_index)] if int(team.current_phase_index) < len(phases) else None
        if not current_phase or current_phase.type != "task" or current_phase.task_id != task_id:
            raise HTTPException(403, "Вы можете просматривать только текущую задачу.")

        task = db.get(Task, task_id)
        if not task: raise HTTPException(404, "Задача не найдена")

        task_file = TASKS_DIR / str(task_id) / "task.txt"
        if not task_file.exists(): raise HTTPException(404, "Файл условия не найден")

        raw_text = task_file.read_text(encoding="utf-8")

        lines = raw_text.strip().split('\n')
        if lines: lines[0] = f"# {lines[0]}"
        text = '\n'.join(lines)

        # 1. Базовые заголовки
        text = text.replace("Условие:", "**Условие:**")
        text = text.replace("Формат входных данных", "### Формат входных данных")
        text = text.replace("Формат выходных данных", "### Формат выходных данных")
        text = text.replace("Ограничение по времени:", "> **Ограничение по времени:**")

        # 2. Умная обработка примеров
        html_after = ""
        html_before = ""

        if "Примеры" in text:
            parts = text.split("Примеры")
            before_text = parts[0] + "### Примеры\n\n"
            after = parts[1].strip()

            html_before = markdown.markdown(before_text, extensions=['nl2br', 'tables'])

            if "|" in after:
                html_after = markdown.markdown(after, extensions=['tables'])
            else:
                delimiter_in = "Входные данные" if "Входные данные" in after else "Ввод"
                delimiter_out = "Выходные данные" if "Выходные данные" in after else "Вывод"

                blocks = re.split(rf'{delimiter_in}\s*', after)

                if len(blocks) > 1:
                    for i, block in enumerate(blocks[1:]):
                        subparts = block.split(delimiter_out)
                        if len(subparts) == 2:
                            in_data = subparts[0].strip()
                            out_data = subparts[1].strip()

                            if not in_data and not out_data:
                                continue

                            html_after += f"""
                            <div class="mb-6 last:mb-0">
                                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    <div>
                                        <div class="text-cyan text-xs font-bold mb-1">{delimiter_in}:</div>
                                        <pre class="bg-[#0b0f19] p-3 rounded-lg border border-line/50 text-sm text-slate-300 font-mono overflow-x-auto whitespace-pre">{in_data}</pre>
                                    </div>
                                    <div>
                                        <div class="text-magenta text-xs font-bold mb-1">{delimiter_out}:</div>
                                        <pre class="bg-[#0b0f19] p-3 rounded-lg border border-line/50 text-sm text-slate-300 font-mono overflow-x-auto whitespace-pre">{out_data}</pre>
                                    </div>
                                </div>
                            </div>
                            """
                else:
                    after_fmt = after.replace('\n', '<br>')
                    html_after = f"<div class='font-mono text-sm text-slate-300 leading-loose'>{after_fmt}</div>"

            examples_box = f"""
            <div class="bg-[#0a0e14] border border-line rounded-xl overflow-hidden mt-4 shadow-lg">
                <div class="bg-panel border-b border-line px-4 py-2 flex items-center gap-2">
                    <div class="w-2.5 h-2.5 rounded-full bg-[#ff5f56]"></div>
                    <div class="w-2.5 h-2.5 rounded-full bg-[#ffbd2e]"></div>
                    <div class="w-2.5 h-2.5 rounded-full bg-[#27c93f]"></div>
                    <div class="text-[10px] text-slate-500 font-mono ml-2 uppercase tracking-widest">test_cases</div>
                </div>
                <div class="p-4 md:p-6 overflow-x-auto">
                    {html_after}
                </div>
            </div>
            """
            html_statement = html_before + examples_box
        else:
            html_statement = markdown.markdown(text, extensions=['nl2br', 'tables'])

        return {"id": task_id, "title": task.title, "statement": html_statement, "max_points": task.points_max}

check_lock = threading.Lock()

@app.post("/api/team/submissions")
async def submit_code(request: Request):
    with Session(engine) as db:
        team = get_current_team(request, db)
        participant = get_current_participant(request, db)
        gs = db.query(GlobalSettings).first()
        phases = db.query(Phase).order_by(Phase.order_index).all()

        if team.started_at is None:
            raise HTTPException(403, "Ваша команда еще не стартовала (ожидание полной посадки).")

        if not gs.is_started or gs.is_paused or team.is_paused or team.finished_at:
            raise HTTPException(403, "Соревнование остановлено.")

        # Индекс фазы берём у КОМАНДЫ, а не у глобальных настроек
        if team.current_phase_index >= len(phases):
            raise HTTPException(403, "Соревнование завершено.")

        current_phase = phases[int(team.current_phase_index)]  # type: ignore

        if current_phase.type == "sport":
            raise HTTPException(403, "Сейчас перерыв на спортивное задание.")

        data = await request.json()
        tid, code = data.get("task_id"), data.get("code", "")

        # Разрешаем посылку для текущей задачи и для предыдущей (grace 30 сек)
        allowed_task_ids = set()
        if current_phase.type == "task" and current_phase.task_id:
            allowed_task_ids.add(current_phase.task_id)

        if team.current_phase_index > 0 and team.phase_started_at:
            prev_phase = phases[team.current_phase_index - 1]
            if prev_phase.type == "task" and prev_phase.task_id:
                elapsed_in_new_phase = (utc_now() - team.phase_started_at).total_seconds()
                if elapsed_in_new_phase < 30:
                    allowed_task_ids.add(prev_phase.task_id)

        if tid not in allowed_task_ids:
            if current_phase.type == "sport":
                raise HTTPException(403, "Сейчас перерыв на спортивное задание.")
            raise HTTPException(403, "Вы можете решать только текущую активную задачу.")

        task_db = db.get(Task, tid)
        if not task_db: raise HTTPException(404, "Задача не найдена")

        tf = TASKS_DIR / str(tid)
        temp = tf / "temp" / f"team_{team.id}"
        if temp.exists(): shutil.rmtree(temp)
        temp.mkdir(parents=True)
        if (tf / "tests.json").exists(): shutil.copy(tf / "tests.json", temp / "tests.json")
        (temp / "solution.py").write_text(code, encoding="utf-8")

        # Загружаем тесты, чтобы посчитать время
        tests_count = 10
        if (tf / "tests.json").exists():
            try:
                import json
                t_data = json.loads((tf / "tests.json").read_text(encoding="utf-8"))
                tests_count = len(t_data.get("tests", []))
            except:
                pass

        orig, backup = tf / "solution.py", tf / "solution_backup.py"

        # БЛОКИРОВКА: не даем двум ученикам проверяться одновременно
        with check_lock:
            try:
                if orig.exists(): shutil.move(orig, backup)
                shutil.copy(temp / "solution.py", orig)

                # Динамический таймаут: 10 сек + 3 сек на каждый тест
                dynamic_timeout = 10 + (tests_count * 3)
                res = subprocess.run([sys.executable, "main.py", "tasks", "--only", str(tid)], cwd=str(ORCESTRATOR_DIR),
                                     capture_output=True, text=True, timeout=dynamic_timeout)
                raw_log = res.stdout + "\n" + res.stderr
            except Exception as e:
                raw_log = str(e)
            finally:
                if backup.exists():
                    shutil.move(backup, orig)
                elif orig.exists():
                    orig.unlink()
                if temp.exists(): shutil.rmtree(temp)

        score = 0
        time_ms = 0.0
        memory_mb = 0.0
        status = "WA"
        details = ""

        # 1. Парсим общий балл
        # 1. Парсим общий балл
        match = re.search(r"(?:Результат|итог):\s*(\d+)/(\d+)", raw_log, re.IGNORECASE)
        if match:
            score = int(match.group(1))
            max_score = int(match.group(2))
            if score == max_score and max_score > 0:
                status = "OK"
        elif "Нет файла solution.py" in raw_log:
            status = "CE"
            details = "Ошибка: Файл с решением не найден."
        elif "Некорректный JSON" in raw_log or "список 'tests' пуст" in raw_log:
            status = "RE"
            details = "Внутренняя ошибка: Тесты к задаче повреждены или отсутствуют."

        # 2. Если не ОК, выясняем причину
        if status != "OK":
            # Ищем первую ошибку в логе
            fail_lines = re.findall(r"\[FAIL] #(\d+):\s*(.*)", raw_log)
            if fail_lines:
                test_id, err_msg = fail_lines[0]

                if "wrong output" in err_msg:
                    status = "WA"
                    details = f"Неверный ответ на тесте #{test_id}."
                elif "TIMEOUT" in err_msg or "Time Limit" in err_msg:
                    status = "TL"
                    details = f"Превышено время выполнения на тесте #{test_id}."
                elif "MEMORY_LIMIT" in err_msg:
                    status = "TL"  # Обычно превышение памяти считают как TL или ML
                    details = f"Превышена память на тесте #{test_id}."
                elif "SyntaxError" in err_msg or "IndentationError" in err_msg:
                    status = "CE"
                    details = f"Ошибка компиляции:\n{err_msg}"
                else:
                    # Сюда попадут ВСЕ остальные ошибки (NameError, KeyError, ZeroDivision, кастомные исключения и т.д.)
                    status = "RE"
                    details = f"Ошибка на тесте #{test_id}:\n{err_msg}"
            else:
                # Если лог необычный (например, упал сам сервер)
                status = "RE"
                details = "Внутренняя ошибка сервера проверки."

        # 3. Парсим время и память
        times = re.findall(r"time=([\d.]+)ms", raw_log)
        mems = re.findall(r"mem=([\d.]+)MB", raw_log)
        if times: time_ms = max(float(t) for t in times)
        if mems: memory_mb = max(float(m) for m in mems)

        # --- РАСЧЕТ ВРЕМЕНИ В ИГРЕ (добавьте эту строку) ---
        time_spent = int((utc_now() - team.started_at).total_seconds()) if team.started_at else 0

        old_subs = db.query(Submission).filter_by(participant_id=participant.id, task_id=tid).all()
        for old_sub in old_subs:
            if old_sub.score is None or old_sub.score <= score:
                db.delete(old_sub)

        db.add(Submission(
            team_id=team.id,
            participant_id=participant.id,
            task_id=tid,
            code=code,
            score=score,
            time_ms=time_ms,
            memory_mb=memory_mb,
            time_spent=time_spent,
            status=status
        ))
        db.commit()
        await manager.broadcast("update_rating")
        # Возвращаем только безопасную информацию, без сырых логов
        return {"status": "ok", "verdict": status, "score": score, "details": details, "max_points": task_db.points_max}


@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        gs = db.query(GlobalSettings).first()
        teams = db.query(Team).all()
        phases = db.query(Phase).order_by(Phase.order_index).all()
        participants = db.query(Participant).all()

        participants_data = []
        for p in participants:
            subs = db.query(Submission).filter_by(participant_id=p.id).all()
            best_subs = {}
            for s in subs:
                if s.task_id not in best_subs or (s.score or 0) > (best_subs[s.task_id].score or 0):
                    best_subs[s.task_id] = s

            code_score = sum((s.score or 0) for s in best_subs.values())

            # Считаем время и память ТОЛЬКО для задач, где есть баллы > 0
            valid_times = [s.time_ms for s in best_subs.values() if (s.score or 0) > 0 and s.time_ms is not None]
            valid_mems = [s.memory_mb for s in best_subs.values() if (s.score or 0) > 0 and s.memory_mb is not None]

            best_time = min(valid_times) if valid_times else 999999
            best_mem = min(valid_mems) if valid_mems else 999999

            participants_data.append({
                "id": p.id, "name": p.name, "team_id": p.team_id,
                "team_name": next((t.name for t in teams if t.id == p.team_id), "—"),
                "score": code_score, "best_time": best_time, "best_mem": best_mem,
            })

        sorted_py = sorted(participants_data, key=lambda p: (-p["score"], p["best_time"], p["best_mem"]))
        for idx, p in enumerate(sorted_py):
            p["place_python"] = idx + 1

        sport_phases = [p for p in phases if p.type == "sport"]
        sport_ranks_sum = {p.id: 0 for p in participants}

        for sp in sport_phases:
            results = db.query(SportResult).filter_by(phase_id=sp.id).all()
            res_dict = {r.participant_id: r.attempts for r in results if r.participant_id}

            def sport_sort_key(p):
                val = res_dict.get(p.id, None)
                # Все, у кого нет результата, отправляются в конец списка
                if val is None: return (1, 0)
                return (0, -val if sp.sport_direction == 'more' else val)

            sorted_sp = sorted(participants, key=sport_sort_key)
            current_rank = 1
            for i, p in enumerate(sorted_sp):
                if i > 0:
                    prev_val = res_dict.get(sorted_sp[i - 1].id, None)
                    curr_val = res_dict.get(p.id, None)
                    # Если результаты отличаются - меняем ранг. Если оба None - ранг не меняется!
                    if curr_val != prev_val:
                        current_rank = i + 1
                sport_ranks_sum[p.id] += current_rank

        sorted_sport = sorted(participants, key=lambda p: sport_ranks_sum[p.id])
        participant_place_sport = {p.id: idx + 1 for idx, p in enumerate(sorted_sport)}

        for p in participants_data:
            p["place_sport"] = participant_place_sport.get(p["id"], 99)
            p["final_place"] = p["place_python"] + p["place_sport"]
            p["sport_attempts"] = sum(
                [r.attempts for r in db.query(SportResult).filter_by(participant_id=p["id"]).all()])

        final_sorted = sorted(participants_data, key=lambda x: (x["final_place"], x["place_python"]))

        teams_data = []
        for t in teams:
            current_phase = phases[int(t.current_phase_index)] if t.current_phase_index < len(phases) else None  # type: ignore
            phase_name = "Ожидание"
            time_left = 0
            if current_phase:
                phase_name = current_phase.sport_name if current_phase.type == 'sport' else f"Задача {current_phase.task_id}"
                if t.phase_started_at:
                    elapsed = (utc_now() - t.phase_started_at).total_seconds()
                    time_left = max(0, int(current_phase.duration_seconds - elapsed))

            total_time = int((utc_now() - t.started_at).total_seconds()) if t.started_at else 0

            teams_data.append({
                "id": t.id, "name": t.name,
                "score": sum(p["score"] for p in participants_data if p["team_id"] == t.id),
                "is_paused": t.is_paused, "is_active": t.is_active,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                "current_phase_index": t.current_phase_index,
                "phase_limit": t.phase_limit if t.phase_limit > 0 else settings.max_phases_per_team,
                "phase_name": phase_name, "phase_time_left": time_left, "total_time": total_time,
                "team_size": db.query(Participant).filter(Participant.team_id == t.id).count(),
                "team_max": settings.team_size, "is_full": t.is_full, "force_started": t.force_started
            })

        current_phase_for_admin = 0
        latest_start = None
        for t in teams:
            if t.phase_started_at and t.current_phase_index < len(phases):
                if latest_start is None or t.phase_started_at > latest_start:
                    latest_start = t.phase_started_at
                    current_phase_for_admin = t.current_phase_index

        return {
            "participants": final_sorted,
            "teams": teams_data,
            "global_is_started": gs.is_started,
            "global_is_paused": gs.is_paused,
            "current_phase": current_phase_for_admin
        }


@app.post("/api/admin/timer/global")
async def toggle_global_timer(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        gs = db.query(GlobalSettings).first()

        if "is_started" in data:
            gs.is_started = data["is_started"]

        if "is_paused" in data:
            new_paused = data["is_paused"]
            if new_paused and not gs.is_paused:
                gs.paused_at = utc_now()
            elif not new_paused and gs.is_paused and gs.paused_at:
                delta = (utc_now() - gs.paused_at).total_seconds()
                for t in db.query(Team).all():
                    if t.started_at: t.started_at += timedelta(seconds=delta)
                    if t.phase_started_at: t.phase_started_at += timedelta(seconds=delta)
                gs.paused_at = None
            gs.is_paused = new_paused

        db.commit()
        await manager.broadcast("timer_changed")
        return {"status": "ok"}


@app.post("/api/admin/team/{team_id}/timer")
async def toggle_team_timer(team_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        team = db.get(Team, team_id)
        if not team: raise HTTPException(404)

        if "is_paused" in data:
            new_paused = data["is_paused"]
            if new_paused and not team.is_paused:
                team.paused_at = utc_now()
            elif not new_paused and team.is_paused and team.paused_at:
                delta = (utc_now() - team.paused_at).total_seconds()
                if team.started_at: team.started_at += timedelta(seconds=delta)
                if team.phase_started_at: team.phase_started_at += timedelta(seconds=delta)
                team.paused_at = None
            team.is_paused = new_paused

        if "force_finish" in data:
            team.finished_at = utc_now()
        db.commit()
        await manager.broadcast("timer_changed")
        return {"status": "ok"}


@app.post("/api/admin/teams")
async def admin_create_team(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        team_name = data.get("name")
        participants = data.get("participants", [])  # [{name, email}]

        if db.query(Organization).filter(Organization.name == team_name).first():
            raise HTTPException(400, "Команда с таким названием уже существует")

        if not team_name: raise HTTPException(400, "Укажите название")

        org = Organization(name=team_name, password_hash=get_password_hash(secrets.token_urlsafe(6)))
        db.add(org)
        db.flush()
        team = Team(name=team_name, organization_id=org.id, is_active=True)
        db.add(team)
        db.flush()

        created_participants = []
        for p in participants:
            p_name = p.get("name", "").strip()
            p_email = p.get("email", "").strip().lower()
            if not p_name or not p_email: continue

            # Проверка на уникальность email
            if db.query(Participant).filter(Participant.email == p_email).first():
                continue  # пропускаем дубликат

            code = secrets.token_urlsafe(6)
            while db.query(Participant).filter(Participant.login_code == code).first():
                code = secrets.token_urlsafe(6)

            db.add(Participant(name=p_name, email=p_email, login_code=code, team_id=team.id))
            created_participants.append({"name": p_name, "email": p_email, "login_code": code})

        if len(created_participants) >= settings.team_size:
            team.is_full = True

        db.commit()
        return {"status": "ok", "team_name": team_name, "participants": created_participants}


@app.post("/api/admin/teams/{team_id}/force_start")
async def admin_force_start_team(team_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        team = db.get(Team, team_id)
        if not team: raise HTTPException(404)

        team.force_started = True

        if team.started_at is None:
            team.started_at = utc_now()
            team.current_phase_index = 0
            team.phase_started_at = utc_now()
        db.commit()
        await manager.broadcast("timer_changed")
        return {"status": "ok"}


@app.post("/api/admin/teams/{team_id}/delete")
async def admin_delete_team(team_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        team = db.get(Team, team_id)
        if not team: raise HTTPException(404, "Команда не найдена")
        org = db.get(Organization, team.organization_id)
        db.query(Submission).filter_by(team_id=team.id).delete()
        db.query(SportResult).filter_by(team_id=team.id).delete()
        db.query(Participant).filter_by(team_id=team.id).delete()
        db.delete(team)
        if org: db.delete(org)
        db.commit()
        await manager.broadcast("update_rating")
        return {"status": "ok"}


@app.get("/api/admin/tasks")
async def admin_get_tasks(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        tasks = db.query(Task).order_by(Task.order_index).all()
        result = []
        for t in tasks:
            task_file = TASKS_DIR / str(t.id) / "task.txt"
            tests_file = TASKS_DIR / str(t.id) / "tests.json"
            statement = task_file.read_text(encoding="utf-8") if task_file.exists() else ""
            tests_json = tests_file.read_text(encoding="utf-8") if tests_file.exists() else "{}"
            result.append({"id": t.id, "title": t.title, "points_max": t.points_max, "statement": statement,
                           "tests_json": tests_json})
        return result


@app.post("/api/admin/tasks")
async def admin_create_task(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        max_id = max([t.id for t in db.query(Task).all()] + [0]) + 1
        tf = TASKS_DIR / str(max_id)
        tf.mkdir(parents=True, exist_ok=True)
        statement = data.get("statement", "")
        (tf / "task.txt").write_text(statement, encoding="utf-8")
        (tf / "tests.json").write_text(data.get("tests_json", "{}"), encoding="utf-8")

        title_raw = statement.split('\n')[0] if statement else f"Задача {max_id}"
        db.add(Task(id=max_id, order_index=max_id, title=title_raw, statement=statement, points_max=10, is_active=True))
        db.commit()
        sync_tasks_from_disk()
        await manager.broadcast("tasks_changed")
        return {"status": "ok", "id": max_id}


@app.post("/api/admin/tasks/{task_id}/edit")
async def admin_edit_task(task_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        tf = TASKS_DIR / str(task_id)
        if not tf.exists(): raise HTTPException(404, "Папка задачи не найдена")
        (tf / "task.txt").write_text(data.get("statement", ""), encoding="utf-8")
        (tf / "tests.json").write_text(data.get("tests_json", "{}"), encoding="utf-8")
        sync_tasks_from_disk()
        await manager.broadcast("tasks_changed")
        return {"status": "ok"}


@app.post("/api/admin/tasks/{task_id}/delete")
async def admin_delete_task(task_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        tf = TASKS_DIR / str(task_id)
        if tf.exists(): shutil.rmtree(tf)
        db.query(Submission).filter_by(task_id=task_id).delete()
        sync_tasks_from_disk()
        await manager.broadcast("tasks_changed")
        return {"status": "ok"}


# --- РЕДАКТИРОВАНИЕ ФАЗЫ ---
@app.post("/api/admin/phases/{phase_id}/edit")
async def admin_edit_phase(phase_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        phase = db.get(Phase, phase_id)
        if not phase: raise HTTPException(404, "Фаза не найдена")

        if "task_id" in data: phase.task_id = data["task_id"]
        if "sport_name" in data: phase.sport_name = data["sport_name"]
        if "duration_seconds" in data: phase.duration_seconds = int(data["duration_seconds"])
        if "sport_direction" in data: phase.sport_direction = data["sport_direction"]

        db.commit()
        return {"status": "ok"}


# --- ПЕРЕМЕЩЕНИЕ ФАЗ (сохранение порядка) ---
@app.post("/api/admin/phases/reorder")
async def admin_reorder_phases(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        gs = db.query(GlobalSettings).first()
        if gs.is_started:
            raise HTTPException(400, "Нельзя менять порядок фаз после старта олимпиады!")
        data = await request.json()
        phase_ids = data.get("phase_ids", [])

        for idx, pid in enumerate(phase_ids):
            phase = db.get(Phase, pid)
            if phase:
                phase.order_index = idx
        db.commit()
        return {"status": "ok"}


@app.post("/api/team/run")
async def run_virtual(request: Request):
    with Session(engine) as db:
        team = get_current_team(request, db)
        gs = db.query(GlobalSettings).first()
        if gs.is_paused or team.is_paused or team.finished_at:
            raise HTTPException(403, "Таймер остановлен или время вышло.")

        data = await request.json()
        code = data.get("code", "")
        test_input = data.get("input", "")

        # Используем безопасный раннер из оркестратора
        from batch_runner import run_batch

        try:
            # Передаём фиктивный тест, так как run_batch ожидает список тестов
            results = run_batch(
                code,
                [{"id": 1, "input": test_input}],
                timeout_per_test=3.0,
                memory_mb=256,
                isolated=False  # На Windows isolated=True откатывается на seq, на Linux можно True
            )
            r = results[0]

            # Если код выполнился успешно (даже с ошибкой в решении, но без ошибок безопасности)
            if r["rc"] == 0:
                return {"status": "ok", "output": r["out"], "error": ""}
            elif "SecurityError" in r["err"]:
                return {"status": "error", "error": "Запрещено правилами олимпиады:\n" + r["err"]}
            else:
                # Обычная ошибка выполнения кода (например, деление на ноль)
                return {"status": "ok", "output": r["out"], "error": r["err"]}

        except Exception as e:
            return {"status": "error", "error": str(e)}


@app.post("/api/public/register")
async def public_register(request: Request):
    form = await request.form()
    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip().lower()

    if len(name) < 2:
        raise HTTPException(400, "Имя слишком короткое")
    if "@" not in email or len(email) < 5:
        raise HTTPException(400, "Некорректный email")

    with register_lock:
        with Session(engine) as db:
            if db.query(Participant).filter(Participant.email == email).first():
                raise HTTPException(400, "Этот email уже зарегистрирован")

            # Ищем открытую команду (где < 5 человек, еще не стартовала и не завершилась)
            open_team = None
            for t in db.query(Team).filter(
                    Team.is_full == False,
                    Team.started_at == None,  # Команда еще не начинала играть
                    Team.finished_at == None  # Команда еще не завершила олимпиаду
            ).order_by(Team.created_at).all():
                cnt = db.query(Participant).filter(Participant.team_id == t.id).count()
                if cnt < settings.team_size:
                    open_team = t
                    break

            if open_team is None:
                # Создаём новую команду
                org_name = f"Команда {utc_now().strftime('%H%M%S')}"
                org = Organization(name=org_name, password_hash=get_password_hash(secrets.token_urlsafe(6)))
                db.add(org)
                db.flush()
                open_team = Team(name=org_name, organization_id=org.id, is_active=True)
                db.add(open_team)
                db.flush()

            # Генерируем уникальный код для участника
            login_code = secrets.token_urlsafe(6)
            while db.query(Participant).filter(Participant.login_code == login_code).first():
                login_code = secrets.token_urlsafe(6)

            db.add(Participant(name=name, email=email, login_code=login_code, team_id=open_team.id))
            db.flush()

            # Проверяем, набралась ли команда
            cnt = db.query(Participant).filter(Participant.team_id == open_team.id).count()
            if cnt >= settings.team_size:
                open_team.is_full = True

            db.commit()
            return {
                "status": "ok",
                "login_code": login_code,
                "team_name": open_team.name,
                "team_size": cnt,
                "team_max": settings.team_size
            }


# --- УПРАВЛЕНИЕ ФАЗАМИ ---
@app.get("/api/admin/phases")
async def admin_get_phases(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        phases = db.query(Phase).order_by(Phase.order_index).all()
        return [{
            "id": p.id, "order_index": p.order_index, "type": p.type,
            "task_id": p.task_id, "sport_name": p.sport_name,
            "sport_direction": p.sport_direction, # <--- ДОБАВИТЬ ЭТУ СТРОКУ
            "duration_seconds": p.duration_seconds
        } for p in phases]


@app.post("/api/admin/phases")
async def admin_create_phase(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        max_idx = max([p.order_index for p in db.query(Phase).all()] + [-1]) + 1

        if int(data.get("duration_seconds", 0)) <= 0:
            raise HTTPException(400, "Длительность фазы должна быть больше нуля")
        phase = Phase(
            order_index=max_idx,
            type=data.get("type", "task"),
            task_id=data.get("task_id"),
            sport_name=data.get("sport_name"),
            sport_direction=data.get("sport_direction", "more"),  # <- ДОБАВИТЬ
            duration_seconds=int(data.get("duration_seconds", 1800))
        )

        db.add(phase)
        db.commit()
        return {"status": "ok"}


@app.post("/api/admin/phases/{phase_id}/delete")
async def admin_delete_phase(phase_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        phase = db.get(Phase, phase_id)
        if phase:
            db.query(SportResult).filter_by(phase_id=phase_id).delete()  # <--- ЧИСТИМ СПОРТ
            db.delete(phase)
            db.commit()

            # Переиндексируем оставшиеся фазы (чтобы не было дырок 0, 2, 3)
            remaining = db.query(Phase).order_by(Phase.order_index).all()
            for i, p in enumerate(remaining):
                p.order_index = i
            db.commit()
        return {"status": "ok"}


# --- ЭКСПОРТ CSV ---
# --- ЭКСПОРТ CSV ---
@app.get("/api/admin/export")
async def export_csv(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        teams = db.query(Team).all()
        phases = db.query(Phase).order_by(Phase.order_index).all()
        participants = db.query(Participant).all()

        # 1. Считаем place_python для участников
        p_data = []
        for p in participants:
            subs = db.query(Submission).filter_by(participant_id=p.id).all()
            best_subs = {}
            for s in subs:
                if s.task_id not in best_subs or (s.score or 0) > (best_subs[s.task_id].score or 0):
                    best_subs[s.task_id] = s
            p_data.append({
                "id": p.id, "name": p.name,
                "team_name": next((t.name for t in teams if t.id == p.team_id), "—"),
                "score": sum((s.score or 0) for s in best_subs.values()),
                "best_time": min([s.time_ms or 0 for s in best_subs.values()] + [999999]),
                "best_mem": min([s.memory_mb or 0 for s in best_subs.values()] + [999999]),
                "team_id": p.team_id
            })

        sorted_py = sorted(p_data, key=lambda x: (-x["score"], x["best_time"], x["best_mem"]))
        for i, x in enumerate(sorted_py): x["place_python"] = i + 1

        # 2. Считаем place_sport для участников
        sport_phases = [p for p in phases if p.type == "sport"]
        sport_ranks_sum = {p.id: 0 for p in participants}

        for sp in sport_phases:
            results = db.query(SportResult).filter_by(phase_id=sp.id).all()
            res_dict = {r.participant_id: r.attempts for r in results if r.participant_id}

            def sport_sort_key(p):
                val = res_dict.get(p.id, None)
                if val is None: return (1, 0)
                return (0, -val if sp.sport_direction == 'more' else val)

            sorted_sp = sorted(participants, key=sport_sort_key)
            current_rank = 1
            for i, p in enumerate(sorted_sp):
                if i > 0:
                    prev_val = res_dict.get(sorted_sp[i - 1].id, None)
                    curr_val = res_dict.get(p.id, None)
                    if curr_val != prev_val or curr_val is None:
                        current_rank = i + 1
                sport_ranks_sum[p.id] += current_rank

        sorted_sport = sorted(participants, key=lambda p: sport_ranks_sum[p.id])
        participant_place_sport = {p.id: idx + 1 for idx, p in enumerate(sorted_sport)}

        for x in p_data:
            x["place_sport"] = participant_place_sport.get(x["id"], 99)
            x["final_place"] = x["place_python"] + x["place_sport"]
            x["sport_attempts"] = sum(
                [r.attempts for r in db.query(SportResult).filter_by(participant_id=x["id"]).all()])

        final_sorted = sorted(p_data, key=lambda x: (x["final_place"], x["place_python"]))

        # --- ГЕНЕРАЦИЯ CSV ---
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', lineterminator='\r\n')

        # Заголовки (Ученик вместо Команды)
        headers = [
            "Итоговое место", "Ученик", "Команда",
            "Место (Код)", "Баллы (Код)",
            "Место (Спорт)", "Всего подходов (Спорт)"
        ]
        for sp in sport_phases:
            headers.append(f"{sp.sport_name} (Подходы)")
        writer.writerow(headers)

        # Данные
        for row in final_sorted:
            line = [
                row["final_place"], row["name"], row["team_name"],
                row["place_python"], row["score"],
                row["place_sport"], row["sport_attempts"]
            ]

            # Добавляем подходы по каждой спортивной фазе
            for sp in sport_phases:
                r = db.query(SportResult).filter_by(participant_id=row["id"], phase_id=sp.id).first()
                line.append(r.attempts if r else "-")

            writer.writerow(line)

        # BOM для Excel
        body = '\ufeff' + output.getvalue()
        data = body.encode('utf-8')

        return Response(
            content=data,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="results.csv"',
                "Content-Length": str(len(data)),
            },
        )


# --- УПРАВЛЕНИЕ СУДЬЯМИ ---
@app.get("/api/admin/judges")
async def admin_get_judges(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        judges = db.query(Judge).all()
        return [{"id": j.id, "name": j.name, "created_at": j.created_at.isoformat()} for j in judges]


@app.post("/api/admin/judges")
async def admin_create_judge(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        name = data.get("name", "").strip()
        if not name: raise HTTPException(400, "Укажите имя судьи")

        new_password = f"{secrets.randbelow(10000):04d}"
        judge = Judge(name=name, password_hash=get_password_hash(new_password))
        db.add(judge)
        db.commit()
        return {"status": "ok", "password": new_password, "name": name}


@app.post("/api/admin/judges/{judge_id}/delete")
async def admin_delete_judge(judge_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        judge = db.get(Judge, judge_id)
        if judge:
            db.delete(judge)
            db.commit()
        return {"status": "ok"}


@app.post("/api/admin/phases/{phase_id}/start")
async def admin_start_phase(phase_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        gs = db.query(GlobalSettings).first()
        phase = db.get(Phase, phase_id)

        if not phase:
            raise HTTPException(404, "Фаза не найдена")

        data = await request.json()
        team_id = data.get("team_id")

        # Находим реальный индекс фазы (начиная с 0)
        phases = db.query(Phase).order_by(Phase.order_index).all()
        actual_index = next((i for i, p in enumerate(phases) if p.id == phase.id), 0)

        if team_id:
            # Запуск для ОДНОЙ команды
            team = db.get(Team, team_id)
            if not team: raise HTTPException(404, "Команда не найдена")

            team.current_phase_index = actual_index
            team.phase_started_at = utc_now()
            team.finished_at = None
            team.is_paused = False

            # ЛОГИКА: Разрешаем пройти global_limit фаз начиная с этой!
            team.phase_limit = actual_index + settings.max_phases_per_team

            if not team.started_at:
                team.started_at = utc_now()
        else:
            # Запуск для ВСЕХ команд
            gs.is_started = True
            gs.is_paused = False
            for t in db.query(Team).all():
                t.current_phase_index = actual_index
                t.finished_at = None
                t.is_paused = False

                # ЛОГИКА: Разрешаем пройти global_limit фаз начиная с этой!
                t.phase_limit = actual_index + settings.max_phases_per_team

                if t.started_at:
                    t.phase_started_at = utc_now()

        db.commit()
        await manager.broadcast("timer_changed")
        return {"status": "ok"}


@app.get("/staff", response_class=HTMLResponse)
async def staff_page(request: Request):
    token = request.cookies.get("access_token")
    if not token: return RedirectResponse("/")
    payload = decode_token(token)
    if not payload or payload.get("role") != "judge": return RedirectResponse("/")
    return templates.TemplateResponse("staff.html", {"request": request})


@app.get("/api/staff/sport_data")
async def get_staff_sport_data(request: Request):
    with Session(engine) as db:
        get_current_judge(request, db)
        phases = db.query(Phase).filter(Phase.type == "sport").order_by(Phase.order_index).all()
        participants = db.query(Participant).all()
        teams = {t.id: t.name for t in db.query(Team).all()}
        results = db.query(SportResult).all()

        return {
            "phases": [{"id": p.id, "sport_name": p.sport_name, "sport_direction": p.sport_direction} for p in phases],
            "participants": [
                {"id": p.id, "name": p.name, "team_name": teams.get(p.team_id, "—")}
                for p in participants
            ],
            "results": [{"participant_id": r.participant_id, "phase_id": r.phase_id, "attempts": r.attempts} for r in
                        results if r.participant_id]
        }


@app.post("/api/staff/sport_result")
async def save_staff_sport_result(request: Request):
    with Session(engine) as db:
        get_current_judge(request, db)
        data = await request.json()
        participant_id = data.get("participant_id")
        phase_id = data.get("phase_id")
        attempts = int(data.get("attempts", 0))

        participant = db.get(Participant, participant_id)
        if not participant: raise HTTPException(404, "Участник не найден")

        phase = db.get(Phase, phase_id)
        if not phase: raise HTTPException(404, "Фаза не найдена")

        existing = db.query(SportResult).filter_by(participant_id=participant_id, phase_id=phase_id).first()
        if existing:
            existing.attempts = attempts
        else:
            db.add(SportResult(
                team_id=participant.team_id,
                participant_id=participant.id,
                phase_id=phase_id,
                exercise_name=phase.sport_name,
                attempts=attempts
            ))

        db.commit()
        await manager.broadcast("update_rating")
        return {"status": "ok"}


@app.post("/api/staff/phase/{phase_id}/direction")
async def staff_change_direction(phase_id: int, request: Request):
    with Session(engine) as db:
        get_current_judge(request, db)
        data = await request.json()
        new_dir = data.get("direction")
        if new_dir not in ("more", "less"):
            raise HTTPException(400, "Неверное направление")

        phase = db.get(Phase, phase_id)
        if not phase:
            raise HTTPException(404, "Фаза не найдена")

        phase.sport_direction = new_dir
        db.commit()
        return {"status": "ok"}