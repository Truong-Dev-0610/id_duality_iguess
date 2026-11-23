FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m app && mkdir -p /app/data && chown -R app:app /app
USER app
ENV PORT=8000 TRUST_PROXY=1 DB_PATH=/app/data/dualself.db
VOLUME ["/app/data"]
EXPOSE 8000
# Nạp dữ liệu mẫu lúc khởi động (ổ đĩa /app/data có thể được gắn đè khi chạy), rồi chạy gunicorn
CMD ["sh", "-c", "python -m server.cli seed && exec gunicorn -w 2 --timeout 60 -b 0.0.0.0:${PORT} gemini_ai_server:app"]
