"""Multi-AI: bộ định tuyến nhiều nhà cung cấp, tự chuyển khi lỗi/hết hạn mức."""
import json
import time

from ..db import get_setting, now_iso
from .anthropic import AnthropicProvider
from .base import AIResult, Provider, ProviderBlocked, ProviderError
from .gemini import GeminiProvider
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider

KINDS = {
    "gemini": GeminiProvider,
    "openai": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
    "mock": MockProvider,
}


class AllProvidersFailed(Exception):
    pass


def ai_settings(db, cfg):
    s = get_setting(db, "ai", {}) or {}
    return {
        "order": s.get("order") or cfg["AI_PROVIDER_ORDER"],
        "disabled": s.get("disabled") or [],
        "models": s.get("models") or {},
        "allow_user_choice": bool(s.get("allow_user_choice", False)),
    }


def build(name, cfg, models=None):
    pc = dict(cfg["PROVIDERS"].get(name) or {})
    if not pc:
        return None
    if models and models.get(name):
        pc["model"] = models[name]
    return KINDS[pc["kind"]](name, pc, timeout=cfg["AI_TIMEOUT"])


def available(db, cfg):
    """Danh sách nhà cung cấp (không chứa khóa)."""
    st = ai_settings(db, cfg)
    out = []
    names = list(dict.fromkeys(st["order"] + list(cfg["PROVIDERS"])))
    for n in names:
        p = build(n, cfg, st["models"])
        if not p:
            continue
        out.append({
            "name": n, "model": p.model, "configured": p.configured,
            "enabled": n not in st["disabled"] and (n != "mock" or cfg["AI_ALLOW_MOCK"]),
        })
    return out


def _log(db, name, ok, ms, err=""):
    db.execute(
        "INSERT INTO provider_log(provider,ok,latency_ms,error,created_at) VALUES(?,?,?,?,?)",
        (name, 1 if ok else 0, ms, err[:300], now_iso()),
    )
    db.commit()


def generate(db, cfg, system, messages, prefer=None, **opts):
    """Thử lần lượt theo thứ tự ưu tiên; nếu một nhà cung cấp lỗi thì chuyển sang nhà kế tiếp."""
    st = ai_settings(db, cfg)
    order = list(st["order"])
    if prefer and st["allow_user_choice"] and prefer in cfg["PROVIDERS"]:
        order = [prefer] + [o for o in order if o != prefer]
    last_err = "no provider configured"
    for name in order:
        if name in st["disabled"] or (name == "mock" and not cfg["AI_ALLOW_MOCK"]):
            continue
        p = build(name, cfg, st["models"])
        if not p or not p.configured:
            continue
        t0 = time.time()
        try:
            res = p.generate(system, messages, **opts)
            _log(db, name, True, res.latency_ms)
            return res
        except ProviderError as e:
            last_err = str(e)
            _log(db, name, False, int((time.time() - t0) * 1000), last_err)
    raise AllProvidersFailed(last_err)
