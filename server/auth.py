import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import g, jsonify, request

from .db import get_db, now_iso

ROLES = ("student", "parent", "teacher", "admin")
ANIMALS = ["Mèo Mây", "Cún Bông", "Gấu Trúc", "Thỏ Ngủ", "Cá Voi", "Chim Sẻ", "Sóc Nhỏ", "Vịt Vàng", "Cáo Nhỏ", "Rùa Chill"]


def hash_password(pw):
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw, stored):
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, AttributeError):
        return False


def random_alias():
    return f"{secrets.choice(ANIMALS)} #{secrets.randbelow(99):02d}"


def _hash_token(t):
    return hashlib.sha256(t.encode()).hexdigest()


def new_session(db, user_id, days):
    token = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
        (_hash_token(token), user_id, now_iso(), exp),
    )
    db.commit()
    return token


def user_from_token(db, token):
    if not token:
        return None
    row = db.execute(
        """SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
           WHERE s.token_hash=? AND s.expires_at>? AND u.is_active=1""",
        (_hash_token(token), now_iso()),
    ).fetchone()
    return dict(row) if row else None


def drop_session(db, token):
    db.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))
    db.commit()


def public_user(u):
    return {"id": u["id"], "alias": u["alias"], "role": u["role"], "username": u.get("username"), "is_guest": bool(u["is_guest"])}


def bearer():
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def require(*roles):
    """Decorator: bắt buộc đăng nhập và đúng vai trò (nếu có chỉ định)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            db = get_db()
            u = user_from_token(db, bearer())
            if not u:
                return jsonify(error="unauthorized", message="Cần đăng nhập"), 401
            if roles and u["role"] not in roles:
                return jsonify(error="forbidden", message="Bạn không có quyền thực hiện thao tác này"), 403
            g.user = u
            db.execute("UPDATE users SET last_seen=? WHERE id=?", (now_iso(), u["id"]))
            db.commit()
            return fn(*a, **kw)
        return wrapper
    return deco


# ---- giới hạn tần suất (in-memory; dùng Redis nếu chạy nhiều tiến trình)
_hits = defaultdict(deque)


def allow(bucket, key, limit, window):
    now = time.time()
    q = _hits[(bucket, key)]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def reset_limits():
    _hits.clear()


def limited(bucket, limit, window):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            key = (g.user["id"] if "user" in g else None) or request.remote_addr or "?"
            if not allow(bucket, key, limit, window):
                return jsonify(error="rate_limited", message="Bạn thao tác quá nhanh, hãy thử lại sau ít phút"), 429
            return fn(*a, **kw)
        return wrapper
    return deco


USERNAME_RX = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
