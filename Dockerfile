FROM python:3.13-slim
WORKDIR /app
COPY main.py main.html ./
RUN pip install --no-cache-dir fastapi google-genai uvicorn
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
