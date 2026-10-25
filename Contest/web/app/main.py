import secrets
import subprocess
import sys
import re
import json
import shutil
import markdown
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Base, Organization, Team, Task, Submission
from app.security import get_password_hash, verify_password, create_access_token, decode_token

# --- ПУТИ ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ORCESTRATOR_DIR = BASE_DIR / "orcestrator"
TASKS_DIR = ORCESTRATOR_DIR / "tasks"

# --- БД ---
connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
Base.metadata.create_all(bind=engine)

# --- СИНХРОНИЗАЦИЯ ЗАДАЧ ПРИ СТАРТЕ ---
with Session(engine) as db:
    if TASKS_DIR.exists():
        print(f"[sync] Сканируем задачи в {TASKS_DIR}...")

        valid_task_ids = []
        for folder in TASKS_DIR.iterdir():
            if folder.is_dir() and folder.name.isdigit():
                valid_task_ids.append(int(folder.name))

        # Удаляем задачи, которых больше нет в папке
        existing_tasks = db.query(Task).all()
        for et in existing_tasks:
            if et.id not in valid_task_ids:
                print(f"  - Удалена задача {et.id} (нет папки)")
                db.delete(et)
        db.commit()

        # Добавляем/обновляем задачи
        for task_id in valid_task_ids:
            task_folder = TASKS_DIR / str(task_id)
            task_file = task_folder / "task.txt"
            tests_file = task_folder / "tests.json"

            if not task_file.exists():
                continue

            # Читаем заголовок
            raw_text = task_file.read_text(encoding="utf-8").strip()
            first_line = raw_text.split('\n')[0]
            clean_title = re.sub(r'^Задача\s*\d+[\.\:\-]?\s*', '', first_line, flags=re.IGNORECASE).strip()
            if not clean_title:
                clean_title = f"Задача {task_id}"

            # Считаем максимум баллов из tests.json
            max_points = 10
            if tests_file.exists():
                try:
                    tests_data = json.loads(tests_file.read_text(encoding="utf-8"))
                    tests_list = tests_data.get("tests", [])
                    if tests_list:
                        max_points = sum(t.get("points", 0) for t in tests_list)
                except Exception as e:
                    print(f"  ! Ошибка чтения tests.json для задачи {task_id}: {e}")

            existing = db.query(Task).filter(Task.id == task_id).first()
            if not existing:
                new_task = Task(
                    id=task_id, order_index=task_id, title=clean_title,
                    statement="", points_max=max_points, is_active=True
                )
                db.add(new_task)
                print(f"  + Добавлена задача {task_id}: {clean_title} (макс. {max_points} б.)")
            else:
                existing.title = clean_title
                existing.points_max = max_points
                print(f"  ~ Обновлена задача {task_id}: {clean_title} (макс. {max_points} б.)")
    else:
        print(f"[sync] ВНИМАНИЕ: Папка {TASKS_DIR} не найдена!")
    db.commit()

app = FastAPI(title=settings.app_name)
templates = Jinja2Templates(directory="app/templates")


def get_current_team(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Не авторизован")

    payload = decode_token(token)
    if not payload or payload.get("role") != "team":
        raise HTTPException(status_code=401, detail="Неверный токен")

    try:
        team_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Неверный токен")

    team = db.get(Team, team_id)
    if not team or not team.is_active:
        raise HTTPException(status_code=401, detail="Команда недоступна")
    return team


# --- СТРАНИЦЫ ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/team", response_class=HTMLResponse)
async def team_page(request: Request):
    if not request.cookies.get("access_token"):
        return RedirectResponse("/login")
    return templates.TemplateResponse("team.html", {"request": request})


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login")
    response.delete_cookie("access_token")
    return response


# --- API: РЕГИСТРАЦИЯ И ВХОД ---
@app.post("/api/register")
async def register_team(request: Request):
    form = await request.form()
    school = (form.get("school") or "").strip()
    team_name = (form.get("team_name") or "").strip()
    grade = (form.get("grade") or "").strip()
    leader_name = (form.get("leader_name") or "").strip()
    leader_email = (form.get("leader_email") or "").strip()

    if not school or not team_name or not grade or not leader_name or not leader_email:
        raise HTTPException(400, "Заполните все обязательные поля")

    with Session(engine) as db:
        org = db.execute(select(Organization).where(Organization.name == school)).scalar_one_or_none()
        new_password = secrets.token_urlsafe(6)

        if not org:
            org = Organization(name=school, password_hash=get_password_hash(new_password))
            db.add(org)
            db.flush()
        else:
            org.password_hash = get_password_hash(new_password)

        clash = db.execute(
            select(Team).where(Team.name == team_name, Team.organization_id == org.id)).scalar_one_or_none()
        if clash:
            raise HTTPException(400, "Команда с таким названием уже есть в этой школе")

        team = Team(name=team_name, organization_id=org.id, is_active=True)
        db.add(team)
        db.commit()
        return JSONResponse(status_code=201, content={"password": new_password})


@app.post("/api/login")
async def login(request: Request):
    form = await request.form()
    team_name = (form.get("team_name") or "").strip()
    password = (form.get("password") or "").strip()

    with Session(engine) as db:
        team = db.execute(select(Team).where(Team.name == team_name)).scalars().first()
        if not team:
            raise HTTPException(401, "Команда не найдена")

        org = db.get(Organization, team.organization_id)
        if not verify_password(password, org.password_hash):
            raise HTTPException(401, "Неверный пароль организации")

        token = create_access_token({"sub": team.id, "role": "team", "name": team.name})
        response = JSONResponse({"status": "ok"})
        response.set_cookie(
            key="access_token", value=token, httponly=True,
            secure=settings.cookie_secure, samesite=settings.cookie_samesite,
            max_age=settings.access_token_expire_minutes * 60
        )
        return response


# --- API: КАБИНЕТ ---
@app.get("/api/team/me")
async def get_me(request: Request):
    with Session(engine) as db:
        team = get_current_team(request, db)
        all_tasks = db.execute(select(Task).where(Task.is_active == True).order_by(Task.order_index)).scalars().all()

        tasks_out = []
        for t in all_tasks:
            best_sub = db.execute(
                select(Submission).where(Submission.team_id == team.id, Submission.task_id == t.id).order_by(
                    Submission.score.desc())
            ).scalars().first()

            tasks_out.append({
                "id": t.id, "title": t.title, "order_index": t.order_index,
                "max_points": t.points_max, "current_score": best_sub.score if best_sub else 0
            })

        return {"team": {"id": team.id, "name": team.name}, "tasks": tasks_out}


@app.get("/api/team/tasks/{task_id}")
async def get_task(task_id: int, request: Request):
    with Session(engine) as db:
        get_current_team(request, db)
        task_db = db.get(Task, task_id)
        if not task_db:
            raise HTTPException(404, "Задача не найдена")

        task_file = TASKS_DIR / str(task_id) / "task.txt"
        if not task_file.exists():
            raise HTTPException(404, "Файл условия не найден")

        raw_text = task_file.read_text(encoding="utf-8")

        lines = raw_text.strip().split('\n')
        if lines:
            lines[0] = f"# {lines[0]}"
        text = '\n'.join(lines)

        text = text.replace("Условие:", "**Условие:**").replace("Формат ввода:", "**Формат ввода:**")
        text = text.replace("Формат вывода:", "**Формат вывода:**").replace("Уровень сложности:",
                                                                            "**Уровень сложности:**")
        text = text.replace("Тема:", "**Тема:**").replace("Пример:", "### Пример")
        text = text.replace("Ввод:", "`Ввод:`").replace("Вывод:", "`Вывод:`")
        text = text.replace("Ограничения:", "> **Ограничения:**")

        html_statement = markdown.markdown(text, extensions=['nl2br'])

        return {
            "id": task_id, "title": task_db.title, "statement": html_statement,
            "max_points": task_db.points_max
        }


@app.post("/api/team/submissions")
async def submit_code(request: Request):
    with Session(engine) as db:
        team = get_current_team(request, db)
        data = await request.json()
        task_id, code = data.get("task_id"), data.get("code", "")

        if not task_id or not code.strip():
            raise HTTPException(400, "Пустой код или ID задачи")

        task_db = db.get(Task, task_id)
        if not task_db:
            raise HTTPException(404, "Задача не найдена")

        task_folder = TASKS_DIR / str(task_id)
        temp_folder = task_folder / "temp" / f"team_{team.id}"

        # Очищаем старую временную папку
        if temp_folder.exists():
            shutil.rmtree(temp_folder)
        temp_folder.mkdir(parents=True, exist_ok=True)

        # Копируем нужные для чекера файлы
        if (task_folder / "tests.json").exists():
            shutil.copy(task_folder / "tests.json", temp_folder / "tests.json")
        if (task_folder / "task.txt").exists():
            shutil.copy(task_folder / "task.txt", temp_folder / "task.txt")

        # Записываем код команды
        (temp_folder / "solution.py").write_text(code, encoding="utf-8")

        # --- ВРЕМЕННАЯ ПОДМЕНА ДЛЯ ЧЕКЕРА ---
        original_solution = task_folder / "solution.py"
        backup_solution = task_folder / "solution_backup.py"

        try:
            if original_solution.exists():
                shutil.move(original_solution, backup_solution)

            shutil.copy(temp_folder / "solution.py", original_solution)

            result = subprocess.run(
                [sys.executable, "main.py", "tasks", "--only", str(task_id)],
                cwd=str(ORCESTRATOR_DIR), capture_output=True, text=True, timeout=30
            )
            raw_log = result.stdout + "\n" + result.stderr

        except subprocess.TimeoutExpired:
            raw_log = "Ошибка: Проверка заняла слишком много времени (таймаут)."
        except Exception as e:
            raw_log = f"Ошибка запуска чекера: {e}"

        finally:
            # Восстанавливаем оригинальное состояние
            if backup_solution.exists():
                shutil.move(backup_solution, original_solution)
            else:
                if original_solution.exists():
                    original_solution.unlink()

            if temp_folder.exists():
                shutil.rmtree(temp_folder)

        # --- ОЧИСТКА ЛОГА ---
        clean_log_lines = []
        score = 0

        for line in raw_log.splitlines():
            line = line.strip()
            if not line: continue

            match_total = re.search(r"(?:Результат|итог):\s*(\d+)/(\d+)", line, re.IGNORECASE)
            if match_total:
                score = int(match_total.group(1))

            if "[ OK ]" in line or "[FAIL]" in line:
                clean_log_lines.append(line)
            elif "Error" in line or "Exception" in line:
                clean_log_lines.append(f"  └─ {line}")

        if score == task_db.points_max:
            header = f"✅ РЕШЕНИЕ ПРИНЯТО! Баллы: {score} / {task_db.points_max}"
        else:
            header = f"⚠️ ТЕСТЫ ПРОЙДЕНЫ НЕ ВСЕ. Баллы: {score} / {task_db.points_max}"

        if not clean_log_lines:
            check_output = f"{header}\n\n(Нет детальной информации о тестах)."
        else:
            check_output = f"{header}\n\n" + "\n".join(clean_log_lines)

        # Сохраняем в БД
        sub = Submission(
            team_id=team.id, task_id=task_id, code=code,
            score=score, status="works" if score == task_db.points_max else "broken"
        )
        db.add(sub)
        db.commit()

        return {
            "status": "ok",
            "checker_result": check_output,
            "score": score,
            "max_points": task_db.points_max
        }