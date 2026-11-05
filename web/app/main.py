import secrets
import subprocess
import sys
import re
import json
import shutil
import markdown
import csv
import io
from datetime import datetime
from pathlib import Path
from typing import List
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
# Импортируем все модели
from app.models import Base, AdminUser, GlobalSettings, Organization, Team, Task, Submission, Phase, SportResult, Participant, Judge
from app.security import get_password_hash, verify_password, create_access_token, decode_token
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse, Response
from fastapi import Response

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
        valid_ids.sort()
        # print(f"[SYNC] Найдено папок с задачами: {len(valid_ids)}")

        # 1. Обновляем задачи в БД
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

        # 2. АВТОМАТИЧЕСКАЯ СБОРКА ФАЗ
        # Проверяем, совпадает ли количество фаз с задачами. Если нет (или они пустые) — пересобираем.
        current_phases = db.query(Phase).order_by(Phase.order_index).all()

        # Если фаз нет или их количество не равно (задачи * 2 - 1), пересобираем
        expected_phases_count = len(valid_ids) * 2 - 1 if valid_ids else 0

        if len(current_phases) != expected_phases_count:
            print(f"[SYNC] Пересборка фаз (было {len(current_phases)}, ожидается {expected_phases_count})...")

            # Удаляем старые фазы
            for p in current_phases:
                db.delete(p)
            db.commit()

            # Создаем новые
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
            token = create_access_token({"sub": team.id, "role": "team"})
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
    sync_tasks_from_disk()
    with Session(engine) as db:
        team = get_current_team(request, db)
        gs = db.query(GlobalSettings).first()
        phases = db.query(Phase).order_by(Phase.order_index).all()

        # Если команда зашла впервые, запускаем её личный таймер
        if team.started_at is None and gs.is_started:
            # Ждём полной посадки, если админ не запустил принудительно
            if not team.is_full and not team.force_started:
                tasks = db.execute(
                    select(Task).where(Task.is_active == True).order_by(Task.order_index)).scalars().all()
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

            # Запускаем
            team.started_at = datetime.utcnow()
            team.current_phase_index = 0
            team.phase_started_at = datetime.utcnow()
            db.commit()

        current_phase = None
        time_left = 0
        is_break = False

        # Признак, что команда прошла все фазы (последняя + время вышло)
        is_finished_by_phases = False

        if gs.is_started and phases:
            # Проверяем, не вышло ли время текущей фазы у команды
            if team.current_phase_index < len(phases):
                current_phase = phases[team.current_phase_index]

                if team.phase_started_at:
                    elapsed = (datetime.utcnow() - team.phase_started_at).total_seconds()
                    time_left = max(0, int(current_phase.duration_seconds - elapsed))

                    # Если время вышло, переключаем на следующую фазу
                    if time_left == 0:
                        if team.current_phase_index < len(phases) - 1:
                            team.current_phase_index += 1
                            team.phase_started_at = datetime.utcnow()
                            db.commit()
                            # Перечитываем данные для новой фазы
                            current_phase = phases[team.current_phase_index]
                            time_left = current_phase.duration_seconds
                        else:
                            # Последняя фаза и время вышло — команда завершила
                            if team.finished_at is None:
                                team.finished_at = datetime.utcnow()
                                db.commit()
                            is_finished_by_phases = True

                is_break = (current_phase.type == "sport")

        # Считаем общее время в олимпиаде
        total_time = 0
        if team.started_at:
            total_time = int((datetime.utcnow() - team.started_at).total_seconds())

        tasks = db.execute(select(Task).where(Task.is_active == True).order_by(Task.order_index)).scalars().all()
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
        team = get_current_team(request, db)
        teams = db.query(Team).all()

        rows = []
        for t in teams:
            subs = db.query(Submission).filter_by(team_id=t.id).all()
            best_scores: dict[int, Submission] = {}
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
                "id": t.id, "name": t.name, "school": t.school or "",
                "code_score": code_score,
                "total_score": code_score,  # для совместимости с фронтом
                "is_me": (t.id == team.id),
            })

        rows.sort(key=lambda r: -r["code_score"])
        for i, r in enumerate(rows, 1):
            r["place"] = i

        my_place = next((r["place"] for r in rows if r["is_me"]), None)
        return {"teams": rows, "my_place": my_place}


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
        phases = db.query(Phase).order_by(Phase.order_index).all()

        if not gs.is_started or gs.is_paused or team.is_paused or team.finished_at:
            raise HTTPException(403, "Соревнование остановлено.")

        # Индекс фазы берём у КОМАНДЫ, а не у глобальных настроек
        if team.current_phase_index >= len(phases):
            raise HTTPException(403, "Соревнование завершено.")

        current_phase = phases[team.current_phase_index]

        if current_phase.type == "sport":
            raise HTTPException(403, "Сейчас перерыв на спортивное задание.")

        data = await request.json()
        tid, code = data.get("task_id"), data.get("code", "")

        if tid != current_phase.task_id:
            raise HTTPException(403, "Вы можете решать только текущую активную задачу.")

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
        time_ms = 0.0
        memory_mb = 0.0
        status = "WA"
        details = ""

        # 1. Парсим общий балл
        match = re.search(r"(?:Результат|итог):\s*(\d+)/(\d+)", raw_log, re.IGNORECASE)
        if match:
            score = int(match.group(1))
            max_score = int(match.group(2))
            if score == max_score and max_score > 0:
                status = "OK"

        # 2. Если не ОК, выясняем причину
        if status != "OK":
            # Ищем первую ошибку в логе
            fail_lines = re.findall(r"\[FAIL\] #(\d+):\s*(.*)", raw_log)
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
        times = re.findall(r"time=([\d\.]+)ms", raw_log)
        mems = re.findall(r"mem=([\d\.]+)MB", raw_log)
        if times: time_ms = max(float(t) for t in times)
        if mems: memory_mb = max(float(m) for m in mems)

        # --- РАСЧЕТ ВРЕМЕНИ В ИГРЕ (добавьте эту строку) ---
        time_spent = int((datetime.utcnow() - team.started_at).total_seconds()) if team.started_at else 0

        old_subs = db.query(Submission).filter_by(team_id=team.id, task_id=tid).all()
        for old_sub in old_subs:
            if (old_sub.score or 0) <= score:
                db.delete(old_sub)
            else:
                old_sub.code = "# Код удален для экономии места (сохранен лучший результат)"

        # --- СОХРАНЕНИЕ В БАЗУ ---
        db.add(Submission(
            team_id=team.id,
            task_id=tid,
            code=code,
            score=score,
            time_ms=time_ms,
            memory_mb=memory_mb,
            time_spent=time_spent,
            status=status # <--- ДОБАВИТЬ ЭТУ СТРОКУ
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

        # 1. Собираем базовую инфу и баллы по Python
        teams_data = {}
        for t in teams:
            subs = db.execute(select(Submission).where(Submission.team_id == t.id)).scalars().all()
            best_subs = {}
            for s in subs:
                if s.task_id not in best_subs or (s.score or 0) > (best_subs[s.task_id].score or 0):
                    best_subs[s.task_id] = s

            code_score = sum((s.score or 0) for s in best_subs.values())
            # Время и память лучшей посылки (для тай-брейка Python)
            best_time = min([s.time_ms or 0 for s in best_subs.values()] + [999999])
            best_mem = min([s.memory_mb or 0 for s in best_subs.values()] + [999999])

            total_time = int((datetime.utcnow() - t.started_at).total_seconds()) if t.started_at else 0
            time_left = 0
            current_phase = phases[t.current_phase_index] if t.current_phase_index < len(phases) else None
            phase_name = "Ожидание"
            if current_phase:
                phase_name = current_phase.sport_name if current_phase.type == 'sport' else f"Задача {current_phase.task_id}"
                if t.phase_started_at:
                    elapsed = (datetime.utcnow() - t.phase_started_at).total_seconds()
                    time_left = max(0, int(current_phase.duration_seconds - elapsed))

            teams_data[t.id] = {
                "id": t.id, "name": t.name,
                "score": code_score,
                "best_time": best_time, "best_mem": best_mem,
                "is_paused": t.is_paused, "is_active": t.is_active,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                "current_phase_index": t.current_phase_index,
                "phase_name": phase_name, "phase_time_left": time_left, "total_time": total_time,
                "team_size": db.query(Participant).filter(Participant.team_id == t.id).count(),
                "team_max": settings.team_size, "is_full": t.is_full, "force_started": t.force_started
            }

        # 2. Считаем place_python
        sorted_py = sorted(teams, key=lambda t: (-teams_data[t.id]["score"], teams_data[t.id]["best_time"],
                                                 teams_data[t.id]["best_mem"]))
        for idx, t in enumerate(sorted_py):
            teams_data[t.id]["place_python"] = idx + 1

        # 3. Считаем place_sport (Олимпийская система - сумма мест по фазам)
        sport_phases = [p for p in phases if p.type == "sport"]
        sport_ranks_sum = {t.id: 0 for t in teams}

        if sport_phases:
            for sp in sport_phases:
                results = db.query(SportResult).filter_by(phase_id=sp.id).all()
                res_dict = {r.team_id: r.attempts for r in results}

                # Сортируем команды для текущей спорт-фазы
                def sport_sort_key(t):
                    val = res_dict.get(t.id, None)
                    if val is None: return (1, 0)  # Нет результата -> худшие
                    return (0, -val if sp.sport_direction == 'more' else val)

                sorted_sp = sorted(teams, key=sport_sort_key)

                # Раздаем места (1, 2, 2, 4...)
                current_rank = 1
                for i, t in enumerate(sorted_sp):
                    if i > 0:
                        prev_val = res_dict.get(sorted_sp[i - 1].id, None)
                        curr_val = res_dict.get(t.id, None)
                        if curr_val != prev_val or curr_val is None:
                            current_rank = i + 1

                    sport_ranks_sum[t.id] += current_rank

        # 4. Считаем place_sport на основе суммы рангов
        sorted_sport = sorted(teams, key=lambda t: sport_ranks_sum[t.id])
        for idx, t in enumerate(sorted_sport):
            teams_data[t.id]["place_sport"] = idx + 1
            teams_data[t.id]["sport_score"] = sum(
                [r.attempts for r in db.query(SportResult).filter_by(team_id=t.id).all()])  # Сумма подходов (для инфы)

        # 5. Итоговое место (Сумма мест)
        for t_id, data in teams_data.items():
            data["final_place"] = data.get("place_python", 99) + data.get("place_sport", 99)

        # Сортируем итоговый массив для админки (по итоговому месту)
        # Сортируем итоговый массив для админки (по итоговому месту)
        final_sorted = sorted(teams_data.values(), key=lambda x: (x["final_place"], x["place_python"]))

        # Определяем «активную» фазу для подсветки в админке:
        # берём фазу у команды, которая зашла позже всех.
        current_phase_for_admin = 0
        latest_start = None
        for t in teams:
            if t.phase_started_at and t.current_phase_index < len(phases):
                if latest_start is None or t.phase_started_at > latest_start:
                    latest_start = t.phase_started_at
                    current_phase_for_admin = t.current_phase_index

        return {
            "teams": final_sorted,
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
            if gs.is_started:

                # Берём первую фазу (или текущую, если уже шла)
                phases = db.query(Phase).order_by(Phase.order_index).all()
                first_phase = phases[0] if phases else None

                for t in db.query(Team).all():
                    if not t.started_at:
                        t.started_at = datetime.utcnow()

                    # Автоматически ставим команду на первую фазу,
                    # чтобы её таймер пошёл сразу после глобального старта
                    if first_phase is not None:
                        t.current_phase_index = first_phase.order_index
                        t.phase_started_at = datetime.utcnow()

        if "is_paused" in data:
            gs.is_paused = data["is_paused"]

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
        participants = data.get("participants", [])  # [{name, email}]

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
            team.started_at = datetime.utcnow()
            team.current_phase_index = 0
            team.phase_started_at = datetime.utcnow()
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

    with Session(engine) as db:
        if db.query(Participant).filter(Participant.email == email).first():
            raise HTTPException(400, "Этот email уже зарегистрирован")

        # Ищем открытую команду (где < 5 человек)
        open_team = None
        for t in db.query(Team).filter(Team.is_full == False).order_by(Team.created_at).all():
            cnt = db.query(Participant).filter(Participant.team_id == t.id).count()
            if cnt < settings.team_size:
                open_team = t
                break

        if open_team is None:
            # Создаём новую команду
            org_name = f"Команда {datetime.utcnow().strftime('%H%M%S')}"
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
            db.delete(phase)
            db.commit()
        return {"status": "ok"}


# --- ЭКСПОРТ CSV ---
@app.get("/api/admin/export")
async def export_csv(request: Request):
    with Session(engine) as db:
        get_current_admin(request, db)

        # Получаем те же данные, что и для админки
        gs = db.query(GlobalSettings).first()
        teams = db.query(Team).all()
        phases = db.query(Phase).order_by(Phase.order_index).all()

        teams_data = {}
        for t in teams:
            subs = db.execute(select(Submission).where(Submission.team_id == t.id)).scalars().all()
            best_subs = {}
            for s in subs:
                if s.task_id not in best_subs or (s.score or 0) > (best_subs[s.task_id].score or 0):
                    best_subs[s.task_id] = s

            code_score = sum((s.score or 0) for s in best_subs.values())
            best_time = min([s.time_ms or 0 for s in best_subs.values()] + [999999])
            best_mem = min([s.memory_mb or 0 for s in best_subs.values()] + [999999])

            teams_data[t.id] = {
                "name": t.name,
                "score": code_score,
                "best_time": best_time,
                "best_mem": best_mem,
            }

        # Считаем place_python
        sorted_py = sorted(teams, key=lambda t: (-teams_data[t.id]["score"], teams_data[t.id]["best_time"],
                                                 teams_data[t.id]["best_mem"]))
        for idx, t in enumerate(sorted_py):
            teams_data[t.id]["place_python"] = idx + 1

        # Считаем place_sport
        sport_phases = [p for p in phases if p.type == "sport"]
        sport_ranks_sum = {t.id: 0 for t in teams}

        for sp in sport_phases:
            results = db.query(SportResult).filter_by(phase_id=sp.id).all()
            res_dict = {r.team_id: r.attempts for r in results}

            def sport_sort_key(t):
                val = res_dict.get(t.id, None)
                if val is None: return (1, 0)
                return (0, -val if sp.sport_direction == 'more' else val)

            sorted_sp = sorted(teams, key=sport_sort_key)

            current_rank = 1
            for i, t in enumerate(sorted_sp):
                if i > 0:
                    prev_val = res_dict.get(sorted_sp[i - 1].id, None)
                    curr_val = res_dict.get(t.id, None)
                    if curr_val != prev_val or curr_val is None:
                        current_rank = i + 1
                sport_ranks_sum[t.id] += current_rank

        sorted_sport = sorted(teams, key=lambda t: sport_ranks_sum[t.id])
        for idx, t in enumerate(sorted_sport):
            teams_data[t.id]["place_sport"] = idx + 1
            teams_data[t.id]["sport_attempts"] = sum(
                [r.attempts for r in db.query(SportResult).filter_by(team_id=t.id).all()])

        # Итоговое место
        for t_id, data in teams_data.items():
            data["final_place"] = data.get("place_python", 99) + data.get("place_sport", 99)

        # Сортируем по итоговому месту
        final_sorted = sorted(teams_data.values(), key=lambda x: (x["final_place"], x["place_python"]))

        # --- ГЕНЕРАЦИЯ CSV ---
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', lineterminator='\r\n')

        # Заголовки
        headers = [
            "Итоговое место", "Команда",
            "Место (Код)", "Баллы (Код)",
            "Место (Спорт)", "Всего подходов (Спорт)"
        ]
        for sp in sport_phases:
            headers.append(f"{sp.sport_name} (Подходы)")

        writer.writerow(headers)

        # Данные
        for row in final_sorted:
            line = [
                row["final_place"], row["name"],
                row["place_python"], row["score"],
                row["place_sport"], row["sport_attempts"]
            ]

            for sp in sport_phases:
                # Получаем подходы для конкретной фазы
                t = next((x for x in teams if x.name == row["name"]), None)
                if t:
                    r = db.query(SportResult).filter_by(team_id=t.id, phase_id=sp.id).first()
                    line.append(r.attempts if r else "-")
                else:
                    line.append("-")

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
        team_id = data.get("team_id")  # None, если для всех

        if team_id:
            # Запуск для конкретной команды
            team = db.get(Team, team_id)
            if not team: raise HTTPException(404, "Команда не найдена")

            team.current_phase_index = phase.order_index
            team.phase_started_at = datetime.utcnow()
            if not team.started_at:
                team.started_at = datetime.utcnow()
        else:
            # Запуск для ВСЕХ команд
            gs.is_started = True
            gs.is_paused = False
            for t in db.query(Team).all():
                t.current_phase_index = phase.order_index
                t.phase_started_at = datetime.utcnow()
                if not t.started_at:
                    t.started_at = datetime.utcnow()

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
        # Отдаем все спортивные фазы
        phases = db.query(Phase).filter(Phase.type == "sport").order_by(Phase.order_index).all()
        # Отдаем все команды (только активные)
        teams = db.query(Team).filter(Team.is_active == True).all()
        # Отдаем все существующие результаты
        results = db.query(SportResult).all()

        return {
            "phases": [{"id": p.id, "sport_name": p.sport_name, "sport_direction": p.sport_direction} for p in phases],
            "teams": [{"id": t.id, "name": t.name} for t in teams],
            "results": [{"team_id": r.team_id, "phase_id": r.phase_id, "attempts": r.attempts} for r in results]
        }


@app.post("/api/staff/sport_result")
async def save_staff_sport_result(request: Request):
    with Session(engine) as db:
        get_current_judge(request, db)
        data = await request.json()
        team_id = data.get("team_id")
        phase_id = data.get("phase_id")
        attempts = int(data.get("attempts", 0))

        phase = db.get(Phase, phase_id)
        if not phase: raise HTTPException(404, "Фаза не найдена")

        existing = db.query(SportResult).filter_by(team_id=team_id, phase_id=phase_id).first()
        if existing:
            existing.attempts = attempts
        else:
            db.add(SportResult(team_id=team_id, phase_id=phase_id, exercise_name=phase.sport_name, attempts=attempts))

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