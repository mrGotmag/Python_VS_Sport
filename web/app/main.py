import secrets
import subprocess
import sys
import re
import json
import shutil
import markdown
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Base, AdminUser, GlobalSettings, Organization, Team, Task, Submission
from app.security import get_password_hash, verify_password, create_access_token, decode_token


# --- УМНЫЙ ПОИСК ПУТЕЙ ---
def find_orcestrator_dir():
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "orcestrator").exists() and (parent / "orcestrator").is_dir():
            return parent / "orcestrator"
        if (parent / "orcestrator" / "tasks").exists():
            return parent / "orcestrator"
        if (parent / "tasks").exists() and parent.name == "orcestrator":
            return parent
    return current.parent.parent.parent / "orcestrator"


ORCESTRATOR_DIR = find_orcestrator_dir()
TASKS_DIR = ORCESTRATOR_DIR / "tasks"

print(f"[INIT] Путь к orcestrator: {ORCESTRATOR_DIR}")
print(f"[INIT] Путь к задачам: {TASKS_DIR}")

# --- БД ---
connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name)
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
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


def sync_tasks_from_disk():
    with Session(engine) as db:
        if not TASKS_DIR.exists():
            print(f"[WARN] Папка {TASKS_DIR} не существует!")
            return

        valid_ids = [int(f.name) for f in TASKS_DIR.iterdir() if f.is_dir() and f.name.isdigit()]
        print(f"[SYNC] Найдено папок с задачами: {len(valid_ids)}")

        for et in db.query(Task).all():
            if et.id not in valid_ids:
                db.delete(et)
        db.commit()

        for tid in valid_ids:
            f = TASKS_DIR / str(tid) / "task.txt"
            if not f.exists(): continue
            raw = f.read_text(encoding="utf-8").strip()
            title = re.sub(r'^Задача\s*\d+[\.\:\-]?\s*', '', raw.split('\n')[0], flags=re.IGNORECASE).strip()

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


def cleanup_temp_folders():
    """Удаляет все временные папки проверок при старте сервера."""
    if not TASKS_DIR.exists():
        return
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


# Инициализация при старте
sync_tasks_from_disk()
cleanup_temp_folders()

with Session(engine) as db:
    if not db.query(GlobalSettings).first():
        db.add(GlobalSettings(id=1, is_started=False, is_paused=False, total_duration_seconds=4 * 60 * 60))
        db.commit()


def get_current_team(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token: raise HTTPException(401, "Нет токена")
    payload = decode_token(token)
    if not payload or payload.get("role") != "team": raise HTTPException(401, "Неверный токен")
    team = db.get(Team, int(payload.get("sub")))
    if not team or not team.is_active: raise HTTPException(401, "Команда недоступна")
    return team


def get_current_admin(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token: raise HTTPException(401, "Нет токена")
    payload = decode_token(token)
    if not payload or payload.get("role") != "admin": raise HTTPException(403, "Нужен токен админа")
    return db.get(AdminUser, int(payload.get("sub")))


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
    if not request.cookies.get("access_token"): return RedirectResponse("/")
    return templates.TemplateResponse("team.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not request.cookies.get("access_token"): return RedirectResponse("/")
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


@app.get("/api/rating")
async def get_rating():
    """Эндпоинт для таблицы лидеров."""
    with Session(engine) as db:
        teams = db.query(Team).all()

        rating = []
        for team in teams:
            best_subs = db.query(Submission).filter_by(team_id=team.id).all()
            team_scores = {}
            last_submit = None

            for s in best_subs:
                # Обновляем лучший балл по задаче
                if s.task_id not in team_scores or s.score > team_scores[s.task_id]:
                    team_scores[s.task_id] = s.score
                # Ищем время последней сдачи
                if last_submit is None or s.created_at > last_submit:
                    last_submit = s.created_at

            total_score = sum(team_scores.values())
            solved_count = sum(1 for score in team_scores.values() if score > 0)

            rating.append({
                "team_name": team.name,
                "total_score": total_score,
                "solved_count": solved_count,
                "last_submit": last_submit.isoformat() if last_submit else None
            })

        # Сортируем: сначала по очкам (убывание), потом по времени последней сдачи (возрастание)
        rating.sort(key=lambda x: (-x["total_score"], x["last_submit"] or "9999-12-31T23:59:59"))
        return rating


@app.get("/api/team/me")
async def get_me(request: Request):
    sync_tasks_from_disk()
    with Session(engine) as db:
        team = get_current_team(request, db)
        gs = db.query(GlobalSettings).first()
        tasks = db.execute(select(Task).where(Task.is_active == True).order_by(Task.order_index)).scalars().all()

        rem = gs.total_duration_seconds
        is_started = gs.is_started

        if is_started and team.started_at:
            elapsed = (datetime.utcnow() - team.started_at).total_seconds()
            if team.is_paused and team.paused_at:
                elapsed -= (datetime.utcnow() - team.paused_at).total_seconds()
            rem = max(0, int(gs.total_duration_seconds - elapsed))
        elif not is_started:
            rem = gs.total_duration_seconds

        tasks_out = []
        for t in tasks:
            best_sub = db.query(Submission).filter_by(team_id=team.id, task_id=t.id).order_by(
                Submission.score.desc()).first()
            tasks_out.append({
                "id": t.id, "title": t.title, "order_index": t.order_index, "max_points": t.points_max,
                "current_score": best_sub.score if best_sub else 0,
                "time_spent": best_sub.time_spent if best_sub else 0
            })

        return {
            "team": {"name": team.name, "is_paused": team.is_paused,
                     "finished_at": team.finished_at.isoformat() if team.finished_at else None},
            "global": {"is_started": is_started, "is_paused": gs.is_paused},
            "contest": {"remaining_seconds": rem},
            "tasks": tasks_out
        }


@app.get("/api/team/tasks/{task_id}")
async def get_task_detail(task_id: int, request: Request):
    with Session(engine) as db:
        get_current_team(request, db)
        task = db.get(Task, task_id)
        if not task: raise HTTPException(404, "Задача не найдена")
        task_file = TASKS_DIR / str(task_id) / "task.txt"
        if not task_file.exists(): raise HTTPException(404, "Файл условия не найден")
        raw_text = task_file.read_text(encoding="utf-8")
        lines = raw_text.strip().split('\n')
        if lines: lines[0] = f"# {lines[0]}"
        text = '\n'.join(lines)
        text = text.replace("Условие:", "**Условие:**").replace("Формат ввода:", "**Формат ввода:**")
        text = text.replace("Формат вывода:", "**Формат вывода:**").replace("Пример:", "### Пример")
        text = text.replace("Ввод:", "`Ввод:`").replace("Вывод:", "`Вывод:`").replace("Ограничения:",
                                                                                      "> **Ограничения:**")
        html_statement = markdown.markdown(text, extensions=['nl2br'])
        return {"id": task_id, "title": task.title, "statement": html_statement, "max_points": task.points_max}


@app.post("/api/team/submissions")
async def submit_code(request: Request):
    with Session(engine) as db:
        team = get_current_team(request, db)
        gs = db.query(GlobalSettings).first()
        if gs.is_paused or team.is_paused or team.finished_at:
            raise HTTPException(403, "Таймер остановлен или время вышло.")

        data = await request.json()
        tid, code = data.get("task_id"), data.get("code", "")
        task_db = db.get(Task, tid)
        if not task_db: raise HTTPException(404, "Задача не найдена")

        tf = TASKS_DIR / str(tid)
        temp = tf / "temp" / f"team_{team.id}"
        if temp.exists(): shutil.rmtree(temp)
        temp.mkdir(parents=True)
        if (tf / "tests.json").exists(): shutil.copy(tf / "tests.json", temp / "tests.json")
        (temp / "solution.py").write_text(code, encoding="utf-8")

        orig, backup = tf / "solution.py", tf / "solution_backup.py"
        try:
            if orig.exists(): shutil.move(orig, backup)
            shutil.copy(temp / "solution.py", orig)
            res = subprocess.run([sys.executable, "main.py", "tasks", "--only", str(tid)], cwd=str(ORCESTRATOR_DIR),
                                 capture_output=True, text=True, timeout=30)
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
        match = re.search(r"(?:Результат|итог):\s*(\d+)/(\d+)", raw_log, re.IGNORECASE)
        if match: score = int(match.group(1))

        time_spent = int((datetime.utcnow() - team.started_at).total_seconds()) if team.started_at else 0

        # --- ОЧИСТКА СТАРЫХ ПОПЫТОК В БД ---
        # Сохраняем полный код только для лучшего решения, чтобы база не разрасталась
        old_subs = db.query(Submission).filter_by(team_id=team.id, task_id=tid).all()
        for old_sub in old_subs:
            if old_sub.score <= score:
                db.delete(old_sub)  # Новая попытка лучше, старую удаляем
            else:
                old_sub.code = "# Код удален для экономии места (сохранен лучший результат)"

        db.add(Submission(team_id=team.id, task_id=tid, code=code, score=score, time_spent=time_spent))
        db.commit()
        await manager.broadcast("update_rating")
        return {"status": "ok", "score": score, "checker_result": raw_log, "max_points": task_db.points_max}


# --- АДМИНКА ---
@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        gs = db.query(GlobalSettings).first()
        teams = db.query(Team).all()

        teams_data = []
        for t in teams:
            best_subs = db.execute(select(Submission).where(Submission.team_id == t.id)).scalars().all()
            total_score = sum({s.task_id: s.score for s in best_subs}.values())
            rem = gs.total_duration_seconds
            if gs.is_started and t.started_at:
                elapsed = (datetime.utcnow() - t.started_at).total_seconds()
                if t.is_paused and t.paused_at: elapsed -= (datetime.utcnow() - t.paused_at).total_seconds()
                rem = max(0, int(gs.total_duration_seconds - elapsed))

            teams_data.append({
                "id": t.id, "name": t.name, "score": total_score,
                "is_paused": t.is_paused, "is_active": t.is_active,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                "remaining_seconds": rem
            })

        teams_data.sort(key=lambda x: x["score"], reverse=True)
        return {"teams": teams_data, "global_is_started": gs.is_started, "global_is_paused": gs.is_paused,
                "total_duration": gs.total_duration_seconds}


@app.post("/api/admin/timer/global")
async def toggle_global_timer(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        gs = db.query(GlobalSettings).first()

        if "is_started" in data:
            gs.is_started = data["is_started"]
            if gs.is_started:
                for t in db.query(Team).all():
                    if not t.started_at: t.started_at = datetime.utcnow()
        if "is_paused" in data: gs.is_paused = data["is_paused"]
        if "duration_seconds" in data: gs.total_duration_seconds = data["duration_seconds"]

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
            team.is_paused = data["is_paused"]
            team.paused_at = datetime.utcnow() if team.is_paused else None
        if "force_finish" in data: team.finished_at = datetime.utcnow()
        db.commit()
        await manager.broadcast("timer_changed")
        return {"status": "ok"}


@app.post("/api/admin/teams")
async def admin_create_team(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        data = await request.json()
        team_name = data.get("name")
        if not team_name: raise HTTPException(400, "Укажите название")
        new_password = secrets.token_urlsafe(6)
        org = Organization(name=team_name, password_hash=get_password_hash(new_password))
        db.add(org)
        db.flush()
        team = Team(name=team_name, organization_id=org.id, is_active=True)
        db.add(team)
        db.commit()
        return {"status": "ok", "password": new_password, "team_name": team_name}


@app.post("/api/admin/teams/{team_id}/delete")
async def admin_delete_team(team_id: int, request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)
        team = db.get(Team, team_id)
        if not team: raise HTTPException(404, "Команда не найдена")
        org = db.get(Organization, team.organization_id)

        # Каскадное удаление решений
        db.query(Submission).filter_by(team_id=team.id).delete()

        db.delete(team)
        if org: db.delete(org)
        db.commit()
        await manager.broadcast("update_rating")
        return {"status": "ok"}


@app.get("/api/admin/tasks")
async def admin_get_tasks(request: Request):
    sync_tasks_from_disk()
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

        # Удаляем все решения, связанные с этой задачей
        db.query(Submission).filter_by(task_id=task_id).delete()

        sync_tasks_from_disk()
        await manager.broadcast("tasks_changed")
        return {"status": "ok"}


# --- ВИРТУАЛЬНЫЙ ЗАПУСК ---
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

        # Создаем временную папку
        temp = TASKS_DIR / "temp" / f"run_{team.id}"
        if temp.exists(): shutil.rmtree(temp)
        temp.mkdir(parents=True)

        sol_file = temp / "solution.py"
        sol_file.write_text(code, encoding="utf-8")

        # Запускаем код в изолированном процессе (таймаут 3 секунды)
        try:
            # Используем sys.executable -I для изоляции
            res = subprocess.run(
                [sys.executable, "-I", str(sol_file)],
                input=test_input,
                capture_output=True,
                text=True,
                timeout=3.0
            )
            output = res.stdout
            error = res.stderr
            return {"status": "ok", "output": output, "error": error}
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Time Limit Exceeded (3.0s)"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
        finally:
            if temp.exists(): shutil.rmtree(temp)

@app.post("/api/public/register")
async def public_register(request: Request):
    form = await request.form()
    team_name = (form.get("team_name") or "").strip()
    if not team_name or len(team_name) < 2: raise HTTPException(400, "Название слишком короткое")

    with Session(engine) as db:
        if db.query(Organization).filter(Organization.name == team_name).first():
            raise HTTPException(400, "Команда уже существует")

        new_password = secrets.token_urlsafe(6)
        org = Organization(name=team_name, password_hash=get_password_hash(new_password))
        db.add(org)
        db.flush()
        team = Team(name=team_name, organization_id=org.id, is_active=True)
        db.add(team)
        db.commit()
        return {"status": "ok", "password": new_password}