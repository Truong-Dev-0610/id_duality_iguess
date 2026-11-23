"""API cho người dùng: xác thực, chat tư vấn, quản lý hội thoại, kiểm tra an toàn."""
import json

from flask import Blueprint, current_app, g, jsonify, request

from . import auth, chat, prompts, providers, safety
from .db import audit, get_db, now_iso

bp = Blueprint("api", __name__, url_prefix="/api")


def _json():
    return request.get_json(silent=True) or {}


def _cfg():
    return current_app.config["DUAL"]


# ------------------------------------------------------------------ hệ thống
@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.get("/config")
def public_config():
    """Cấu hình công khai cho frontend (không chứa bí mật)."""
    db = get_db()
    st = providers.ai_settings(db, _cfg())
    return jsonify(
        moods=prompts.MOODS,
        topics=prompts.TOPICS,
        max_message_chars=_cfg()["MAX_MESSAGE_CHARS"],
        allow_user_choice=st["allow_user_choice"],
        hotlines=safety.load_hotlines(db),
    )


# ------------------------------------------------------------------ xác thực
@bp.post("/auth/guest")
@auth.limited("guest", 20, 3600)
def guest():
    """Học sinh vào ẩn danh, không cần thông tin cá nhân (đúng tinh thần 'thì thầm')."""
    db = get_db()
    uid = db.execute(
        "INSERT INTO users(role,alias,is_guest,created_at) VALUES('student',?,1,?)",
        (auth.random_alias(), now_iso()),
    ).lastrowid
    db.commit()
    token = auth.new_session(db, uid, _cfg()["GUEST_SESSION_DAYS"])
    u = dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    return jsonify(token=token, user=auth.public_user(u))


@bp.post("/auth/register")
@auth.limited("register", 10, 3600)
def register():
    d = _json()
    role = d.get("role", "student")
    username, pw = (d.get("username") or "").strip(), d.get("password") or ""
    if role not in ("student", "parent", "teacher"):
        return jsonify(error="bad_role", message="Vai trò không hợp lệ"), 400
    if role == "teacher":
        code = _cfg()["TEACHER_INVITE_CODE"]
        if not code or d.get("invite_code") != code:
            return jsonify(error="invite_required", message="Giáo viên cần mã mời từ nhà trường"), 403
    if not auth.USERNAME_RX.match(username):
        return jsonify(error="bad_username", message="Tên đăng nhập 3–32 ký tự (chữ, số, _ . -)"), 400
    if len(pw) < 8:
        return jsonify(error="weak_password", message="Mật khẩu tối thiểu 8 ký tự"), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return jsonify(error="taken", message="Tên đăng nhập đã tồn tại"), 409
    uid = db.execute(
        "INSERT INTO users(username,password_hash,role,alias,created_at) VALUES(?,?,?,?,?)",
        (username, auth.hash_password(pw), role, auth.random_alias(), now_iso()),
    ).lastrowid
    db.commit()
    token = auth.new_session(db, uid, _cfg()["SESSION_DAYS"])
    u = dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    return jsonify(token=token, user=auth.public_user(u)), 201


@bp.post("/auth/login")
@auth.limited("login", 10, 600)
def login():
    d = _json()
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username=? AND is_active=1", ((d.get("username") or "").strip(),)).fetchone()
    # luôn tính hash để thời gian phản hồi không lộ việc tài khoản có tồn tại
    ok = auth.verify_password(d.get("password") or "", row["password_hash"] if row else "scrypt$00$00")
    if not row or not ok:
        return jsonify(error="bad_credentials", message="Sai tên đăng nhập hoặc mật khẩu"), 401
    token = auth.new_session(db, row["id"], _cfg()["SESSION_DAYS"])
    return jsonify(token=token, user=auth.public_user(dict(row)))


@bp.post("/auth/logout")
@auth.require()
def logout():
    auth.drop_session(get_db(), auth.bearer())
    return jsonify(ok=True)


@bp.get("/auth/me")
@auth.require()
def me():
    return jsonify(user=auth.public_user(g.user))


# ------------------------------------------------------------------ chat
@bp.get("/providers")
@auth.require()
def list_providers():
    st = providers.ai_settings(get_db(), _cfg())
    if not st["allow_user_choice"]:
        return jsonify(allow_user_choice=False, providers=[])
    items = [{"name": p["name"], "model": p["model"]} for p in providers.available(get_db(), _cfg()) if p["enabled"] and p["configured"]]
    return jsonify(allow_user_choice=True, providers=items)


@bp.post("/chat")
@auth.require()
@auth.limited("chat", 20, 60)
def chat_endpoint():
    d = _json()
    try:
        out = chat.handle_chat(
            get_db(), _cfg(), g.user, d.get("message"),
            conversation_id=d.get("conversation_id"), provider=d.get("provider"), context=d.get("context"),
        )
    except chat.ChatError as e:
        return jsonify(error=e.code, message=e.message), e.status
    return jsonify(out)


@bp.get("/conversations")
@auth.require()
def conversations():
    rows = get_db().execute(
        """SELECT c.id,c.title,c.updated_at,c.max_risk,
                  (SELECT content FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last
           FROM conversations c WHERE c.user_id=? ORDER BY c.updated_at DESC, c.id DESC LIMIT 50""",
        (g.user["id"],),
    ).fetchall()
    return jsonify(conversations=[{**dict(r), "last": (r["last"] or "")[:80]} for r in rows])


def _own_conv(cid):
    return get_db().execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, g.user["id"])).fetchone()


@bp.get("/conversations/<int:cid>")
@auth.require()
def conversation(cid):
    c = _own_conv(cid)
    if not c:
        return jsonify(error="not_found"), 404
    rows = get_db().execute(
        "SELECT id,role,content,risk_level,provider,sources,created_at FROM messages WHERE conversation_id=? ORDER BY id", (cid,)
    ).fetchall()
    msgs = [{**dict(r), "sources": json.loads(r["sources"] or "[]")} for r in rows]
    return jsonify(conversation={"id": c["id"], "title": c["title"]}, messages=msgs)


@bp.patch("/conversations/<int:cid>")
@auth.require()
def rename_conversation(cid):
    if not _own_conv(cid):
        return jsonify(error="not_found"), 404
    title = (_json().get("title") or "").strip()[:80]
    if not title:
        return jsonify(error="bad_title", message="Tiêu đề trống"), 400
    db = get_db()
    db.execute("UPDATE conversations SET title=? WHERE id=?", (title, cid))
    db.commit()
    return jsonify(ok=True)


@bp.delete("/conversations/<int:cid>")
@auth.require()
def delete_conversation(cid):
    if not _own_conv(cid):
        return jsonify(error="not_found"), 404
    db = get_db()
    db.execute("DELETE FROM conversations WHERE id=?", (cid,))
    db.commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------ safety cho các bài đăng / tin nhắn ngoài khung AI
@bp.post("/safety/check")
@auth.limited("safety", 30, 60)
def safety_check():
    """Không lưu nội dung và không gắn với người dùng (giữ ẩn danh); chỉ ghi nhận số lượng theo mức độ."""
    d = _json()
    text = (d.get("text") or "")[: _cfg()["MAX_MESSAGE_CHARS"]]
    src = d.get("source") if d.get("source") in ("post", "dm", "comment") else "post"
    r = safety.assess(text)
    if r.level >= 2:
        db = get_db()
        chat.log_safety_event(db, _cfg(), None, None, src, r, text)
    res = safety.resources_for(r.categories, get_db()) if r.level >= 1 else []
    return jsonify(level=r.level, label=r.label, categories=r.categories, resources=res)
