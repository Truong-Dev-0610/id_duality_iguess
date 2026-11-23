from dataclasses import dataclass


class ProviderError(Exception):
    """Lỗi từ nhà cung cấp AI. Thông điệp KHÔNG được chứa khóa API."""


class ProviderBlocked(ProviderError):
    """Nhà cung cấp từ chối nội dung (bộ lọc an toàn của họ)."""


@dataclass
class AIResult:
    text: str
    model: str
    provider: str
    latency_ms: int = 0


class Provider:
    name = "base"
    kind = "base"

    def __init__(self, name, cfg, timeout=25):
        self.name = name
        self.api_key = cfg.get("api_key", "")
        self.model = cfg.get("model", "")
        self.base_url = (cfg.get("base_url") or "").rstrip("/")
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.api_key and self.model)

    def generate(self, system, messages, temperature=0.6, max_tokens=500):
        raise NotImplementedError


def merge_turns(messages):
    """Gộp các lượt liên tiếp cùng vai trò (một số API yêu cầu xen kẽ user/assistant)."""
    out = []
    for m in messages:
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n" + m["content"]
        else:
            out.append({"role": m["role"], "content": m["content"]})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def safe_err(resp):
    """Rút gọn lỗi HTTP, không bao giờ in header/khóa."""
    try:
        j = resp.json()
        msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error") or j.get("message")
    except ValueError:
        msg = None
    return f"HTTP {resp.status_code}: {str(msg or resp.reason)[:200]}"
