"""Lệnh quản trị: python -m server.cli seed | purge --days N | create-admin"""
import argparse
import getpass
import sys

from . import auth, rag
from .config import ROOT, load_config
from .db import connect, init_db, now_iso


def main(argv=None):
    ap = argparse.ArgumentParser(prog="server.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="Nạp tài liệu mẫu trong knowledge_seed/ vào Knowledge Base")
    pg = sub.add_parser("purge", help="Xoá hội thoại cũ (bảo vệ quyền riêng tư)")
    pg.add_argument("--days", type=int, required=True)
    ca = sub.add_parser("create-admin")
    ca.add_argument("username")
    a = ap.parse_args(argv)

    cfg = load_config()
    init_db(cfg["DB_PATH"])
    db = connect(cfg["DB_PATH"])
    if a.cmd == "seed":
        print("Đã thêm", rag.seed_from_dir(db, ROOT / "knowledge_seed"), "tài liệu")
    elif a.cmd == "purge":
        cur = db.execute("DELETE FROM conversations WHERE updated_at < datetime('now', ?)", (f"-{a.days} days",))
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
        db.commit()
        print("Đã xoá", cur.rowcount, "hội thoại")
    elif a.cmd == "create-admin":
        pw = getpass.getpass("Mật khẩu (≥ 8 ký tự): ")
        if len(pw) < 8:
            sys.exit("Mật khẩu quá ngắn")
        db.execute(
            "INSERT INTO users(username,password_hash,role,alias,created_at) VALUES(?,?,?,?,?)",
            (a.username, auth.hash_password(pw), "admin", "Quản trị viên", now_iso()),
        )
        db.commit()
        print("Đã tạo admin", a.username)


if __name__ == "__main__":
    main()
