"""Lõi tư vấn: Safety -> RAG -> Multi-AI -> Safety (đầu ra) -> lưu hội thoại."""
import json

from . import prompts, providers, rag, safety
from .db import now_iso


class ChatError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _recent_high_risk(db, conv_id, window=6):
    rows = db.execute(
        "SELECT risk_level FROM messages WHERE conversation_id=? AND role='user' ORDER BY id DESC LIMIT ?",
        (conv_id, window),
    ).fetchall()
    return any(r["risk_level"] >= 2 for r in rows)


def log_safety_event(db, cfg, user_id, conv_id, source, result, text):
    excerpt = text[:160] if (cfg["SAFETY_STORE_EXCERPT"] and source == "chat") else None
    db.execute(
        "INSERT INTO safety_events(user_id,conversation_id,source,level,categories,excerpt,created_at) VALUES(?,?,?,?,?,?,?)",
        (user_id, conv_id, source, result.level, ",".join(result.categories), excerpt, now_iso()),
    )
    db.commit()


def handle_chat(db, cfg, user, text, conversation_id=None, provider=None, context=None):
    text = (text or "").strip()
    if not text:
        raise ChatError("empty", "Tin nhắn trống")
    if len(text) > cfg["MAX_MESSAGE_CHARS"]:
        raise ChatError("too_long", f"Tin nhắn quá dài (tối đa {cfg['MAX_MESSAGE_CHARS']} ký tự)")
    context = context or {}
    ctx = {
        "mood": context.get("mood") if context.get("mood") in prompts.MOODS else None,
        "topic": context.get("topic") if context.get("topic") in prompts.TOPICS else None,
    }

    ts = now_iso()
    if conversation_id:
        conv = db.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user["id"])).fetchone()
        if not conv:
            raise ChatError("not_found", "Không tìm thấy cuộc trò chuyện", 404)
        conv_id = conv["id"]
    else:
        title = text[:48] + ("…" if len(text) > 48 else "")
        conv_id = db.execute(
            "INSERT INTO conversations(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (user["id"], title, ts, ts),
        ).lastrowid

    # 1) SAFETY (trước AI)
    result = safety.assess(text)
    sticky = _recent_high_risk(db, conv_id)
    eff_level = max(result.level, 2 if sticky else 0)
    cats = result.categories or (["distress"] if eff_level else [])
    db.execute(
        "INSERT INTO messages(conversation_id,role,content,risk_level,mood,topic,created_at) VALUES(?,?,?,?,?,?,?)",
        (conv_id, "user", text, result.level, ctx["mood"], ctx["topic"], ts),
    )
    db.commit()
    if result.level >= 2:
        log_safety_event(db, cfg, user["id"], conv_id, "chat", result, text)

    resources = safety.resources_for(cats, db) if eff_level >= 1 else []
    sources, provider_name, model, latency, flags = [], None, None, 0, []

    if result.level >= 3:
        # 2a) Khủng hoảng: KHÔNG gọi AI, trả mẫu cố định
        reply = safety.crisis_response(user["role"], result.categories, resources, result.third_party)
        provider_name, model = "safety-template", "rule-based"
    else:
        # 2b) RAG + Multi-AI
        hits = rag.search(db, text, user["role"], cfg["RAG_TOP_K"]) if eff_level < 2 else rag.search(db, text, user["role"], 2)
        system = prompts.build_system(user["role"], eff_level, ctx, rag.format_context(hits), result.third_party)
        rows = db.execute(
            "SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
            (conv_id, cfg["HISTORY_TURNS"] * 2),
        ).fetchall()
        history = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        try:
            res = providers.generate(db, cfg, system, history, prefer=provider, temperature=0.5 if eff_level else 0.7, max_tokens=450)
            reply, provider_name, model, latency = res.text, res.provider, res.model, res.latency_ms
            reply, flags = safety.guard_output(reply, eff_level, user["role"])
            if "method_info" in flags:
                provider_name, model = "safety-template", "output-guard"
            else:
                sources = list({h["doc_id"]: {"doc_id": h["doc_id"], "title": h["title"]} for h in hits}.values())
        except providers.AllProvidersFailed:
            reply = safety.FALLBACK_SAFE.format(you="anh/chị" if user["role"] in ("parent", "teacher") else "bạn")
            provider_name, model, flags = "safety-template", "fallback", ["providers_down"]
        if eff_level >= 2:
            reply += safety.resource_footer(resources, user["role"])

    # 3) Lưu phản hồi
    ts2 = now_iso()
    mid = db.execute(
        """INSERT INTO messages(conversation_id,role,content,risk_level,provider,model,latency_ms,sources,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (conv_id, "assistant", reply, eff_level, provider_name, model, latency, json.dumps(sources, ensure_ascii=False), ts2),
    ).lastrowid
    db.execute(
        "UPDATE conversations SET updated_at=?, max_risk=MAX(max_risk,?) WHERE id=?",
        (ts2, result.level, conv_id),
    )
    db.commit()
    return {
        "conversation_id": conv_id,
        "message": {"id": mid, "role": "assistant", "content": reply, "created_at": ts2, "provider": provider_name, "sources": sources},
        "risk": {"level": eff_level, "label": ["none", "watch", "high", "crisis"][eff_level], "categories": cats},
        "resources": resources,
        "flags": flags,
    }
