"""Cấu hình — đọc từ biến môi trường. KHÔNG hard-code khóa API ở bất kỳ đâu."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _bool(v, default=False):
    if v is None or v == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _list(v, default):
    items = [x.strip() for x in (v or "").split(",") if x.strip()]
    return items or default


def _load_dotenv(path):
    """Đọc tệp .env đơn giản (KEY=VALUE). Biến môi trường thật luôn được ưu tiên."""
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def load_config(overrides=None):
    _load_dotenv(ROOT / ".env")
    e = os.environ.get
    cfg = {
        "ROOT": ROOT,
        "ENV": e("APP_ENV", "development"),
        "DB_PATH": e("DB_PATH", str(ROOT / "data" / "dualself.db")),
        "CORS_ORIGINS": _list(e("CORS_ORIGINS"), []),
        "TRUST_PROXY": _bool(e("TRUST_PROXY")),
        "ADMIN_USERNAME": e("ADMIN_USERNAME", ""),
        "ADMIN_PASSWORD": e("ADMIN_PASSWORD", ""),
        "TEACHER_INVITE_CODE": e("TEACHER_INVITE_CODE", ""),
        "SESSION_DAYS": int(e("SESSION_DAYS", "7")),
        "GUEST_SESSION_DAYS": int(e("GUEST_SESSION_DAYS", "30")),
        "MAX_MESSAGE_CHARS": int(e("MAX_MESSAGE_CHARS", "1500")),
        "MAX_UPLOAD_BYTES": int(e("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
        "HISTORY_TURNS": int(e("HISTORY_TURNS", "10")),
        "RAG_TOP_K": int(e("RAG_TOP_K", "4")),
        "AI_TIMEOUT": int(e("AI_TIMEOUT", "25")),
        "AI_ALLOW_MOCK": _bool(e("AI_ALLOW_MOCK"), True),
        "AI_PROVIDER_ORDER": _list(
            e("AI_PROVIDER_ORDER"),
            ["gemini", "groq", "openrouter", "anthropic", "openai", "ollama", "mock"],
        ),
        "SAFETY_STORE_EXCERPT": _bool(e("SAFETY_STORE_EXCERPT"), True),
        # Mỗi nhà cung cấp: kind = giao thức, key/model/base_url lấy từ env.
        "PROVIDERS": {
            "gemini": {"kind": "gemini", "api_key": e("GEMINI_API_KEY", ""),
                       "model": e("GEMINI_MODEL", "gemini-2.5-flash"),
                       "base_url": "https://generativelanguage.googleapis.com/v1beta"},
            "groq": {"kind": "openai", "api_key": e("GROQ_API_KEY", ""),
                     "model": e("GROQ_MODEL", "llama-3.3-70b-versatile"),
                     "base_url": e("GROQ_BASE_URL", "https://api.groq.com/openai/v1")},
            "openrouter": {"kind": "openai", "api_key": e("OPENROUTER_API_KEY", ""),
                           "model": e("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
                           "base_url": e("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")},
            "anthropic": {"kind": "anthropic", "api_key": e("ANTHROPIC_API_KEY", ""),
                          "model": e("ANTHROPIC_MODEL", "claude-haiku-5-5"),
                          "base_url": "https://api.anthropic.com/v1"},
            "openai": {"kind": "openai", "api_key": e("OPENAI_API_KEY", ""),
                       "model": e("OPENAI_MODEL", "gpt-4o-mini"),
                       "base_url": e("OPENAI_BASE_URL", "https://api.openai.com/v1")},
            # Ollama chạy local (miễn phí, không cần key): đặt OLLAMA_MODEL để bật.
            "ollama": {"kind": "openai", "api_key": "local" if e("OLLAMA_MODEL") else "",
                       "model": e("OLLAMA_MODEL", ""),
                       "base_url": e("OLLAMA_BASE_URL", "http://localhost:11434/v1")},
            "mock": {"kind": "mock", "api_key": "n/a", "model": "mock-v1", "base_url": ""},
        },
    }
    if overrides:
        cfg.update(overrides)
    return cfg
