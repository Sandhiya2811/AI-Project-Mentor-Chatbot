"""All SQL lives here. Functions return plain dicts."""
from __future__ import annotations

from database.db import session
from utils.helpers import dumps, loads, now_iso


def _row(r):
    return dict(r) if r is not None else None


def _rows(rs):
    return [dict(r) for r in rs]


# ---- users -------------------------------------------------------------------------------
def get_user() -> dict:
    with session() as c:
        return _row(c.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone())


def update_user(user_id: int, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("name", "preferred_language", "skill_level")}
    if not allowed:
        return
    with session() as c:
        c.execute(f"UPDATE users SET {', '.join(k + '=?' for k in allowed)} WHERE id=?", (*allowed.values(), user_id))


# ---- projects ----------------------------------------------------------------------------
def create_project(user_id, title, idea, objective, domain, programming_language, difficulty, source,
                   tools, requirements, tasks) -> int:
    """Atomically stores a project with its tools, requirements, tasks and progress row."""
    ts = now_iso()
    with session() as c:
        pid = c.execute(
            "INSERT INTO projects(user_id,title,idea,objective,domain,programming_language,difficulty,"
            "roadmap_source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (user_id, title, idea, objective, domain, programming_language, difficulty, source, ts, ts)).lastrowid
        for i, t in enumerate(tools):
            c.execute("INSERT INTO project_requirements(project_id,kind,name,detail,position) VALUES(?,?,?,?,?)",
                      (pid, "tool", t["name"], t.get("role", ""), i))
        for i, text in enumerate(requirements):
            c.execute("INSERT INTO project_requirements(project_id,kind,name,position) VALUES(?,?,?,?)",
                      (pid, "requirement", text, i))
        first_id = None
        for i, t in enumerate(tasks):
            tid = c.execute(
                "INSERT INTO tasks(project_id,position,title,description,expected_output,deliverable_type,"
                "hints_json,checks_json,status) VALUES(?,?,?,?,?,?,?,?,?)",
                (pid, i + 1, t["title"], t["description"], t["expected_output"], t["deliverable_type"],
                 dumps(t.get("hints", [])), dumps(t.get("checks", [])), "active" if i == 0 else "locked")).lastrowid
            first_id = first_id or tid
        c.execute("INSERT INTO project_progress(project_id,total_tasks,completed_tasks,percent,current_task_id,"
                  "last_activity) VALUES(?,?,?,?,?,?)", (pid, len(tasks), 0, 0, first_id, ts))
        return pid


def get_project(pid: int):
    with session() as c:
        return _row(c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())


def list_projects(user_id: int) -> list[dict]:
    with session() as c:
        return _rows(c.execute(
            "SELECT p.*, g.total_tasks, g.completed_tasks, g.percent FROM projects p "
            "LEFT JOIN project_progress g ON g.project_id=p.id WHERE p.user_id=? ORDER BY p.updated_at DESC",
            (user_id,)).fetchall())


def update_project(pid: int, **fields) -> None:
    fields["updated_at"] = now_iso()
    with session() as c:
        c.execute(f"UPDATE projects SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), pid))


def delete_project(pid: int) -> None:
    with session() as c:
        c.execute("DELETE FROM projects WHERE id=?", (pid,))


def list_requirements(pid: int, kind: str | None = None) -> list[dict]:
    with session() as c:
        sql, args = "SELECT * FROM project_requirements WHERE project_id=?", [pid]
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        return _rows(c.execute(sql + " ORDER BY position", args).fetchall())


# ---- tasks / progress --------------------------------------------------------------------
def _task(r):
    d = _row(r)
    if d:
        d["hints"] = loads(d.pop("hints_json"), [])
        d["checks"] = loads(d.pop("checks_json"), [])
    return d


def list_tasks(pid: int) -> list[dict]:
    with session() as c:
        return [_task(r) for r in c.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY position", (pid,))]


def get_task(tid: int):
    with session() as c:
        return _task(c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())


def get_active_task(pid: int):
    with session() as c:
        return _task(c.execute("SELECT * FROM tasks WHERE project_id=? AND status='active' ORDER BY position LIMIT 1",
                               (pid,)).fetchone())


def set_task_status(tid: int, status: str) -> None:
    with session() as c:
        c.execute("UPDATE tasks SET status=?, completed_at=? WHERE id=?",
                  (status, now_iso() if status == "passed" else None, tid))


def increment_attempts(tid: int) -> int:
    with session() as c:
        c.execute("UPDATE tasks SET attempts=attempts+1 WHERE id=?", (tid,))
        return c.execute("SELECT attempts FROM tasks WHERE id=?", (tid,)).fetchone()[0]


def get_progress(pid: int):
    with session() as c:
        return _row(c.execute("SELECT * FROM project_progress WHERE project_id=?", (pid,)).fetchone())


def refresh_progress(pid: int) -> dict:
    with session() as c:
        tasks = c.execute("SELECT id,status FROM tasks WHERE project_id=? ORDER BY position", (pid,)).fetchall()
        total = len(tasks)
        done = sum(1 for t in tasks if t["status"] == "passed")
        current = next((t["id"] for t in tasks if t["status"] == "active"), None)
        pct = round(100.0 * done / total, 1) if total else 0.0
        c.execute("UPDATE project_progress SET total_tasks=?,completed_tasks=?,percent=?,current_task_id=?,"
                  "last_activity=? WHERE project_id=?", (total, done, pct, current, now_iso(), pid))
        c.execute("UPDATE projects SET updated_at=?, status=? WHERE id=?",
                  (now_iso(), "completed" if total and done == total else "active", pid))
    return get_progress(pid)


# ---- submissions / files / reports -------------------------------------------------------
def create_submission(project_id, task_id, attempt_no, notes) -> int:
    with session() as c:
        return c.execute("INSERT INTO student_submissions(project_id,task_id,attempt_no,notes,status,created_at) "
                         "VALUES(?,?,?,?,?,?)", (project_id, task_id, attempt_no, notes, "Pending Review",
                                                 now_iso())).lastrowid


def set_submission_status(sid: int, status: str) -> None:
    with session() as c:
        c.execute("UPDATE student_submissions SET status=? WHERE id=?", (status, sid))


def list_submissions(task_id: int) -> list[dict]:
    with session() as c:
        return _rows(c.execute("SELECT * FROM student_submissions WHERE task_id=? ORDER BY id", (task_id,)))


def add_uploaded_file(submission_id, original_name, stored_path, size, sha, language, kind) -> None:
    with session() as c:
        c.execute("INSERT INTO uploaded_files(submission_id,original_name,stored_path,size_bytes,sha256,"
                  "detected_language,kind,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (submission_id, original_name, stored_path, size, sha, language, kind, now_iso()))


def list_uploaded_files(submission_id: int) -> list[dict]:
    with session() as c:
        return _rows(c.execute("SELECT * FROM uploaded_files WHERE submission_id=?", (submission_id,)))


def add_report(submission_id, task_id, status, rules, static, llm_review, not_performed, report_md) -> int:
    with session() as c:
        return c.execute(
            "INSERT INTO validation_reports(submission_id,task_id,status,rule_results_json,static_results_json,"
            "llm_review_json,not_performed_json,report_md,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (submission_id, task_id, status, dumps(rules), dumps(static), dumps(llm_review), dumps(not_performed),
             report_md, now_iso())).lastrowid


def latest_report(task_id: int):
    with session() as c:
        return _row(c.execute("SELECT * FROM validation_reports WHERE task_id=? ORDER BY id DESC LIMIT 1",
                              (task_id,)).fetchone())


# ---- conversations / messages ------------------------------------------------------------
def create_conversation(user_id, project_id, title, language="") -> int:
    ts = now_iso()
    with session() as c:
        return c.execute("INSERT INTO conversations(user_id,project_id,title,language,created_at,updated_at) "
                         "VALUES(?,?,?,?,?,?)", (user_id, project_id, title, language, ts, ts)).lastrowid


def get_conversation(cid: int):
    with session() as c:
        return _row(c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone())


def get_conversation_for_project(pid: int):
    with session() as c:
        return _row(c.execute("SELECT * FROM conversations WHERE project_id=? ORDER BY updated_at DESC LIMIT 1",
                              (pid,)).fetchone())


def list_conversations(user_id: int, query: str = "") -> list[dict]:
    with session() as c:
        if query.strip():
            like = f"%{query.strip()}%"
            rs = c.execute(
                "SELECT * FROM conversations WHERE user_id=? AND (title LIKE ? OR id IN "
                "(SELECT conversation_id FROM chat_messages WHERE content LIKE ?)) ORDER BY updated_at DESC",
                (user_id, like, like))
        else:
            rs = c.execute("SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC", (user_id,))
        return _rows(rs)


def rename_conversation(cid: int, title: str) -> None:
    with session() as c:
        c.execute("UPDATE conversations SET title=? WHERE id=?", (title.strip() or "Untitled", cid))


def set_conversation_language(cid: int, language: str) -> None:
    with session() as c:
        c.execute("UPDATE conversations SET language=? WHERE id=?", (language, cid))


def delete_conversation(cid: int) -> None:
    with session() as c:
        c.execute("DELETE FROM conversations WHERE id=?", (cid,))


def clear_all_conversations(user_id: int) -> None:
    with session() as c:
        c.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))


def add_message(cid: int, role: str, content: str, kind: str = "chat", metadata: dict | None = None) -> dict:
    ts = now_iso()
    with session() as c:
        mid = c.execute("INSERT INTO chat_messages(conversation_id,role,content,kind,metadata_json,created_at) "
                        "VALUES(?,?,?,?,?,?)", (cid, role, content, kind, dumps(metadata or {}), ts)).lastrowid
        c.execute("UPDATE conversations SET updated_at=? WHERE id=?", (ts, cid))
    return {"id": mid, "conversation_id": cid, "role": role, "content": content, "kind": kind,
            "metadata": metadata or {}, "created_at": ts}


def list_messages(cid: int, limit: int | None = None) -> list[dict]:
    with session() as c:
        if limit:
            rs = c.execute("SELECT * FROM (SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY id DESC "
                           "LIMIT ?) ORDER BY id", (cid, limit))
        else:
            rs = c.execute("SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY id", (cid,))
        out = _rows(rs)
    for m in out:
        m["metadata"] = loads(m.pop("metadata_json"), {})
    return out


# ---- learning notes ----------------------------------------------------------------------
def save_note(project_id, tool_name, language, content_md, doc_url, order_index, source) -> None:
    with session() as c:
        c.execute(
            "INSERT INTO learning_notes(project_id,tool_name,language,content_md,doc_url,order_index,source,"
            "created_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,tool_name) DO UPDATE SET "
            "language=excluded.language, content_md=excluded.content_md, doc_url=excluded.doc_url, "
            "order_index=excluded.order_index, source=excluded.source, created_at=excluded.created_at",
            (project_id, tool_name, language, content_md, doc_url, order_index, source, now_iso()))


def list_notes(project_id: int) -> list[dict]:
    with session() as c:
        return _rows(c.execute("SELECT * FROM learning_notes WHERE project_id=? ORDER BY order_index",
                               (project_id,)))


# ---- activity ----------------------------------------------------------------------------
def log_activity(user_id, project_id, action, detail="") -> None:
    with session() as c:
        c.execute("INSERT INTO activity_logs(user_id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                  (user_id, project_id, action, detail, now_iso()))
