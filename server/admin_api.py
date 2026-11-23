"""API quản trị. Admin: toàn quyền. Teacher: chỉ xem/xử lý cảnh báo an toàn (đã ẩn nội dung)."""
import io

from flask import Blueprint, current_app, g, jsonify, request

from . import auth, providers, rag
from .db import audit, get_db, get_setting, now_iso, set_setting

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _json():
    return request.get_json(silent=True) or {}


def _cfg():
    return current_app.config["DUAL"]


# ------------------------------------------------------------------ thống kê
@bp.get("/stats")
@auth.require("admin")
def stats():
    db = get_db()
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    rows = lambda sql, *a: [dict(r) for r in db.execute(sql, a).fetchall()]
    return jsonify(
        users={r["role"]: r["n"] for r in rows("SELECT role, COUNT(*) n FROM users WHERE is_active=1 GROUP BY role")},
        totals={
            "conversations": one("SELECT COUNT(*) FROM conversations"),
            "messages": one("SELECT COUNT(*) FROM messages"),
            "kb_documents": one("SELECT COUNT(*) FROM kb_documents WHERE is_active=1"),
            "kb_chunks": one("SELECT COUNT(*) FROM kb_chunks"),
            "open_alerts": one("SELECT COUNT(*) FROM safety_events WHERE handled=0 AND level>=2"),
        },
        daily=rows(
            """SELECT substr(created_at,1,10) AS day, COUNT(*) AS messages,
                      COUNT(DISTINCT conversation_id) AS conversations
               FROM messages WHERE role='user' AND created_at >= datetime('now','-14 days')
               GROUP BY day ORDER BY day"""
        ),
        safety_by_level=rows("SELECT level, COUNT(*) n FROM safety_events GROUP BY level ORDER BY level"),
        safety_by_category=rows(
            """SELECT categories AS category, COUNT(*) n FROM safety_events
               WHERE created_at >= datetime('now','-30 days') GROUP BY categories ORDER BY n DESC LIMIT 8"""
        ),
        moods=rows("SELECT mood, COUNT(*) n FROM messages WHERE mood IS NOT NULL GROUP BY mood ORDER BY n DESC"),
        topics=rows("SELECT topic, COUNT(*) n FROM messages WHERE topic IS NOT NULL GROUP BY topic ORDER BY n DESC"),
        providers=rows(
            """SELECT provider, COUNT(*) AS calls, SUM(ok) AS ok, CAST(AVG(latency_ms) AS INT) AS avg_ms
               FROM provider_log WHERE created_at >= datetime('now','-7 days') GROUP BY provider"""
        ),
    )


# ------------------------------------------------------------------ cảnh báo an toàn
@bp.get("/safety")
@auth.require("admin", "teacher")
def safety_list():
    db = get_db()
    only_open = request.args.get("open") == "1"
    sql = """SELECT e.id,e.level,e.categories,e.source,e.handled,e.handled_at,e.note,e.created_at,e.excerpt,
                    e.conversation_id,u.alias
             FROM safety_events e LEFT JOIN users u ON u.id=e.user_id
             WHERE e.level>=2 """ + ("AND e.handled=0 " if only_open else "") + "ORDER BY e.id DESC LIMIT 200"
    items = [dict(r) for r in db.execute(sql).fetchall()]
    if g.user["role"] != "admin":  # giáo viên không xem nội dung hội thoại
        for it in items:
            it.pop("excerpt", None)
            it.pop("conversation_id", None)
    return jsonify(items=items)


@bp.patch("/safety/<int:eid>")
@auth.require("admin", "teacher")
def safety_handle(eid):
    d = _json()
    db = get_db()
    if not db.execute("SELECT 1 FROM safety_events WHERE id=?", (eid,)).fetchone():
        return jsonify(error="not_found"), 404
    db.execute(
        "UPDATE safety_events SET handled=?, handled_by=?, handled_at=?, note=? WHERE id=?",
        (1 if d.get("handled", True) else 0, g.user["id"], now_iso(), (d.get("note") or "")[:300], eid),
    )
    db.commit()
    audit(db, g.user["id"], "safety.handle", eid)
    return jsonify(ok=True)


# ------------------------------------------------------------------ kho kiến thức
def _read_upload(f):
    name = (f.filename or "").lower()
    data = f.read(_cfg()["MAX_UPLOAD_BYTES"] + 1)
    if len(data) > _cfg()["MAX_UPLOAD_BYTES"]:
        raise ValueError("Tệp quá lớn")
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("Máy chủ chưa cài pypdf để đọc PDF")
        return "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    raise ValueError("Chỉ hỗ trợ .txt, .md, .pdf")


@bp.get("/kb")
@auth.require("admin")
def kb_list():
    rows = get_db().execute(
        """SELECT d.id,d.title,d.audience,d.tags,d.source,d.is_active,d.updated_at,
                  (SELECT COUNT(*) FROM kb_chunks c WHERE c.doc_id=d.id) AS chunks,
                  length(d.content) AS size
           FROM kb_documents d ORDER BY d.id DESC"""
    ).fetchall()
    return jsonify(items=[dict(r) for r in rows])


@bp.get("/kb/<int:did>")
@auth.require("admin")
def kb_get(did):
    r = get_db().execute("SELECT * FROM kb_documents WHERE id=?", (did,)).fetchone()
    return (jsonify(dict(r)), 200) if r else (jsonify(error="not_found"), 404)


@bp.post("/kb")
@auth.require("admin")
def kb_create():
    if request.files.get("file"):
        try:
            content = _read_upload(request.files["file"])
        except ValueError as e:
            return jsonify(error="bad_file", message=str(e)), 400
        f = request.form
        title = f.get("title") or request.files["file"].filename
        audience, tags, source = f.get("audience", "all"), f.get("tags", ""), f.get("source", "")
    else:
        d = _json()
        title, content = d.get("title", ""), d.get("content", "")
        audience, tags, source = d.get("audience", "all"), d.get("tags", ""), d.get("source", "")
    if not title.strip() or len(content.strip()) < 20:
        return jsonify(error="bad_doc", message="Cần tiêu đề và nội dung (≥ 20 ký tự)"), 400
    db = get_db()
    did = rag.add_document(db, title, content, audience, tags, source, g.user["id"])
    audit(db, g.user["id"], "kb.create", f"{did}:{title[:60]}")
    return jsonify(id=did), 201


@bp.patch("/kb/<int:did>")
@auth.require("admin")
def kb_update(did):
    d = _json()
    db = get_db()
    row = db.execute("SELECT * FROM kb_documents WHERE id=?", (did,)).fetchone()
    if not row:
        return jsonify(error="not_found"), 404
    aud = d.get("audience", row["audience"])
    db.execute(
        "UPDATE kb_documents SET title=?,audience=?,tags=?,source=?,content=?,is_active=?,updated_at=? WHERE id=?",
        (
            (d.get("title") or row["title"])[:200],
            aud if aud in rag.AUDIENCES else row["audience"],
            (d.get("tags", row["tags"]) or "")[:200],
            (d.get("source", row["source"]) or "")[:300],
            d.get("content") or row["content"],
            1 if d.get("is_active", row["is_active"]) else 0,
            now_iso(), did,
        ),
    )
    db.commit()
    rag.index_document(db, did)
    audit(db, g.user["id"], "kb.update", did)
    return jsonify(ok=True)


@bp.delete("/kb/<int:did>")
@auth.require("admin")
def kb_delete(did):
    db = get_db()
    rag.delete_document(db, did)
    audit(db, g.user["id"], "kb.delete", did)
    return jsonify(ok=True)


@bp.post("/kb/test")
@auth.require("admin")
def kb_test():
    """Thử truy xuất: xem RAG sẽ lấy đoạn nào cho một câu hỏi (kiểm tra chất lượng kho kiến thức)."""
    d = _json()
    hits = rag.search(get_db(), d.get("query", ""), d.get("role", "student"), _cfg()["RAG_TOP_K"])
    return jsonify(hits=[{"doc_id": h["doc_id"], "title": h["title"], "text": h["text"][:300], "score": round(h["score"], 3)} for h in hits])


# ------------------------------------------------------------------ người dùng
@bp.get("/users")
@auth.require("admin")
def users_list():
    rows = get_db().execute(
        "SELECT id,username,alias,role,is_guest,is_active,created_at,last_seen FROM users ORDER BY id DESC LIMIT 300"
    ).fetchall()
    return jsonify(items=[dict(r) for r in rows])


@bp.post("/users")
@auth.require("admin")
def users_create():
    d = _json()
    role, username, pw = d.get("role"), (d.get("username") or "").strip(), d.get("password") or ""
    if role not in auth.ROLES or not auth.USERNAME_RX.match(username) or len(pw) < 8:
        return jsonify(error="bad_input", message="Vai trò, tên đăng nhập (3–32 ký tự) hoặc mật khẩu (≥ 8) không hợp lệ"), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return jsonify(error="taken", message="Tên đăng nhập đã tồn tại"), 409
    uid = db.execute(
        "INSERT INTO users(username,password_hash,role,alias,created_at) VALUES(?,?,?,?,?)",
        (username, auth.hash_password(pw), role, auth.random_alias(), now_iso()),
    ).lastrowid
    db.commit()
    audit(db, g.user["id"], "user.create", f"{uid}:{role}")
    return jsonify(id=uid), 201


@bp.patch("/users/<int:uid>")
@auth.require("admin")
def users_update(uid):
    d = _json()
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return jsonify(error="not_found"), 404
    if uid == g.user["id"] and (d.get("is_active") is False or (d.get("role") and d["role"] != "admin")):
        return jsonify(error="self_lock", message="Không thể tự khoá hoặc hạ quyền chính mình"), 400
    role = d.get("role", row["role"])
    if role not in auth.ROLES:
        return jsonify(error="bad_role"), 400
    active = 1 if d.get("is_active", bool(row["is_active"])) else 0
    db.execute("UPDATE users SET role=?, is_active=? WHERE id=?", (role, active, uid))
    if not active:
        db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    db.commit()
    audit(db, g.user["id"], "user.update", f"{uid}:{role}:{active}")
    return jsonify(ok=True)


# ------------------------------------------------------------------ cấu hình AI (Multi-AI)
@bp.get("/ai")
@auth.require("admin")
def ai_get():
    db = get_db()
    st = providers.ai_settings(db, _cfg())
    return jsonify(settings=st, providers=providers.available(db, _cfg()))


@bp.put("/ai")
@auth.require("admin")
def ai_put():
    d = _json()
    cfg, db = _cfg(), get_db()
    known = set(cfg["PROVIDERS"])
    order = [p for p in (d.get("order") or []) if p in known]
    disabled = [p for p in (d.get("disabled") or []) if p in known]
    models = {k: str(v)[:100] for k, v in (d.get("models") or {}).items() if k in known and v}
    set_setting(db, "ai", {
        "order": order or cfg["AI_PROVIDER_ORDER"], "disabled": disabled, "models": models,
        "allow_user_choice": bool(d.get("allow_user_choice", False)),
    })
    audit(db, g.user["id"], "ai.update", f"order={order} disabled={disabled}")
    return jsonify(ok=True)


@bp.post("/ai/test")
@auth.require("admin")
def ai_test():
    name = _json().get("provider")
    db = get_db()
    st = providers.ai_settings(db, _cfg())
    p = providers.build(name, _cfg(), st["models"])
    if not p or not p.configured:
        return jsonify(ok=False, message="Chưa cấu hình khóa API trên máy chủ"), 400
    try:
        r = p.generate("Trả lời rất ngắn bằng tiếng Việt.", [{"role": "user", "content": "Xin chào"}], max_tokens=40)
        return jsonify(ok=True, model=r.model, latency_ms=r.latency_ms, sample=r.text[:120])
    except providers.ProviderError as e:
        return jsonify(ok=False, message=str(e)), 502


# ------------------------------------------------------------------ hotline
@bp.get("/hotlines")
@auth.require("admin")
def hotlines_get():
    from . import safety
    return jsonify(items=safety.load_hotlines(get_db()))


@bp.put("/hotlines")
@auth.require("admin")
def hotlines_put():
    items = []
    for h in (_json().get("items") or [])[:20]:
        if h.get("name") and h.get("number"):
            items.append({
                "id": str(h.get("id") or h["number"])[:30], "name": str(h["name"])[:100], "number": str(h["number"])[:30],
                "desc": str(h.get("desc", ""))[:200], "hours": str(h.get("hours", ""))[:60],
                "tags": [t for t in h.get("tags", []) if t in ("suicide", "self_harm", "crisis", "abuse", "violence", "bullying", "distress")],
            })
    if not items:
        return jsonify(error="empty", message="Danh sách không được rỗng"), 400
    db = get_db()
    set_setting(db, "hotlines", items)
    audit(db, g.user["id"], "hotlines.update", len(items))
    return jsonify(ok=True)
