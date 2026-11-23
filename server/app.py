"""Flask app factory — phục vụ cả API lẫn giao diện tĩnh hiện có (main.html giữ nguyên)."""
from flask import Flask, jsonify, request, send_from_directory

from . import auth
from .admin_api import bp as admin_bp
from .api import bp as api_bp
from .config import ROOT, load_config
from .db import close_db, connect, init_db, now_iso


def bootstrap_admin(cfg):
    """Tạo tài khoản admin đầu tiên từ biến môi trường (không có mật khẩu mặc định)."""
    if not (cfg["ADMIN_USERNAME"] and cfg["ADMIN_PASSWORD"]):
        return
    if len(cfg["ADMIN_PASSWORD"]) < 8:
        raise RuntimeError("ADMIN_PASSWORD phải có ít nhất 8 ký tự")
    db = connect(cfg["DB_PATH"])
    try:
        if not db.execute("SELECT 1 FROM users WHERE username=?", (cfg["ADMIN_USERNAME"],)).fetchone():
            db.execute(
                "INSERT INTO users(username,password_hash,role,alias,created_at) VALUES(?,?,?,?,?)",
                (cfg["ADMIN_USERNAME"], auth.hash_password(cfg["ADMIN_PASSWORD"]), "admin", "Quản trị viên", now_iso()),
            )
            db.commit()
    finally:
        db.close()


def create_app(overrides=None):
    cfg = load_config(overrides)
    app = Flask(__name__, static_folder=None)
    app.config["DUAL"] = cfg
    app.config["DB_PATH"] = cfg["DB_PATH"]
    app.config["MAX_CONTENT_LENGTH"] = cfg["MAX_UPLOAD_BYTES"] + 64 * 1024
    if cfg["TRUST_PROXY"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    init_db(cfg["DB_PATH"])
    bootstrap_admin(cfg)
    app.teardown_appcontext(close_db)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
            origin = request.headers.get("Origin")
            if origin and origin in cfg["CORS_ORIGINS"]:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
        return resp

    @app.route("/api/<path:_p>", methods=["OPTIONS"])
    def preflight(_p):
        return ("", 204)

    @app.errorhandler(404)
    def nf(_e):
        return (jsonify(error="not_found"), 404) if request.path.startswith("/api/") else ("Not found", 404)

    @app.errorhandler(413)
    def too_big(_e):
        return jsonify(error="too_large", message="Tệp quá lớn"), 413

    @app.errorhandler(500)
    def boom(_e):
        return jsonify(error="server_error", message="Có lỗi phía máy chủ"), 500

    # ---- giao diện tĩnh (không thay đổi tệp hiện có)
    @app.get("/")
    def index():
        return send_from_directory(ROOT, "main.html")

    @app.get("/admin")
    def admin_page():
        return send_from_directory(ROOT, "admin.html")

    @app.get("/style.css")
    def css():
        return send_from_directory(ROOT, "style.css")

    @app.get("/assets/<path:name>")
    def assets(name):
        return send_from_directory(ROOT / "assets", name)

    return app
