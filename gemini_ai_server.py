"""Điểm vào máy chủ (giữ tên tệp gốc của dự án).

Chạy thử:     python gemini_ai_server.py
Triển khai:   gunicorn gemini_ai_server:app
Dù tên tệp còn chữ "gemini", hệ thống hỗ trợ nhiều nhà cung cấp AI (xem server/providers).
"""
import os

from server.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
