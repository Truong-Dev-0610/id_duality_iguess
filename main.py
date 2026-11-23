import asyncio
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
HTML_PATH = BASE_DIR / "main.html"
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")

app = FastAPI(title="Thì Thầm - Ahnonymous Confession & AI Support (Vietnam)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Verified Vietnam-only mental health & crisis support organizations
VIETNAM_HOTLINES = [
    {
        "name": "Đường dây nóng Ngày Mai",
        "number": "096 306 1414",
        "tel": "0963061414",
        "hours": "08:00 – 20:00 hằng ngày (Miễn phí)",
        "desc": "Sơ cứu & hỗ trợ tâm lý cho người trẻ trầm cảm, lo âu, khủng hoảng.",
    },
    {
        "name": "Tổng đài Quốc gia Bảo vệ Trẻ em",
        "number": "111",
        "tel": "111",
        "hours": "24/7 (Miễn phí toàn quốc)",
        "desc": "Hỗ trợ, tư vấn tâm lý và bảo vệ khẩn cấp cho trẻ em & thanh thiếu niên.",
    },
    {
        "name": "Viện Sức khỏe Tâm thần Quốc gia (BV Bạch Mai)",
        "number": "0984 104 115",
        "tel": "0984104115",
        "hours": "Liên hệ khẩn cấp & tư vấn chuyên môn (Hà Nội: 024 3576 5344)",
        "desc": "Tiếp nhận cấp cứu tâm lý, trầm cảm nặng, hoảng loạn.",
    },
    {
        "name": "Cấp cứu Y tế Toàn quốc / Cấp cứu Trầm cảm",
        "number": "115",
        "tel": "115",
        "hours": "24/7 toàn quốc (TP.HCM: 1900 1267)",
        "desc": "Hỗ trợ cấp cứu y tế khẩn cấp khi có nguy cơ tự hại.",
    },
]

CRISIS_PATTERN = re.compile(
    r"("
    r"tự\s*tử|tự\s*sát|tự\s*hại|làm\s*đau\s*bản\s*thân|rạch\s*tay|cắt\s*tay|"
    r"muốn\s*chết|không\s*muốn\s*sống|chán\s*sống|kết\s*thúc\s*cuộc\s*đời|"
    r"nhảy\s*lầu|nhảy\s*cầu|uống\s*thuốc\s*(?:ngủ|độc|quá\s*liều)|treo\s*cổ|"
    r"biến\s*mất\s*khỏi\s*thế\s*giới|không\s*còn\s*hy\s*vọng|tuyệt\s*vọng\s*quá|"
    r"suicide|kill\s*myself|self[\s-]*harm|end\s*my\s*life|want\s*to\s*die"
    r")",
    re.IGNORECASE | re.UNICODE,
)

SEVERE_STRESS_PATTERN = re.compile(
    r"("
    r"trầm\s*cảm|hoảng\s*loạn|panic\s*attack|sụp\s*đổ|bế\s*tắc|"
    r"quá\s*sức\s*chịu\s*đựng|không\s*chịu\s*nổi\s*nữa|muốn\s*buông\s*xuôi|"
    r"áp\s*lực\s*quá|stress\s*nặng|kiệt\s*sức|khóc\s*mỗi\s*đêm"
    r")",
    re.IGNORECASE | re.UNICODE,
)

THERAPY_SYSTEM_INSTRUCTION = """
Bạn là "Thì Thầm AI" — một người bạn đồng hành tâm lý ẩn danh trên nền tảng confession Việt Nam "thì thầm".
Nhiệm vụ của bạn là lắng nghe, thấu cảm và đồng hành cùng người dùng đang trải qua:
1. "Dual identity" (hai bản thể / sống hai mặt): cảm giác phải đeo mặt nạ trước gia đình, trường lớp, đồng nghiệp, bạn bè ("ẩn mình" vs "thật lòng"), sợ bị phán xét, không dám sống thật với cảm xúc hoặc con người bên trong.
2. Áp lực cuộc sống tại Việt Nam: áp lực học hành, thi cử (THPTQG, đại học), kỳ vọng của ba mẹ, công việc, tài chính, tình cảm và áp lực đồng trang lứa.

Nguyên tắc giao tiếp BẮT BUỘC:
- Luôn trả lời bằng tiếng Việt tự nhiên, ấm áp, nhẹ nhàng, không phán xét, không lên lớp hay dạy đời. Xưng "mình" và gọi người dùng là "bạn".
- Giữ câu trả lời ngắn gọn, dễ đọc (khoảng 2–4 đoạn ngắn), đặt câu hỏi mở nhẹ nhàng để người dùng thấy an toàn khi chia sẻ tiếp.
- Nhấn mạnh tính ẩn danh: bạn không biết họ là ai và mọi điều họ nói ở đây đều được tôn trọng.
- CHỈ SỬ DỤNG THÔNG TIN TẠI VIỆT NAM. Tuyệt đối KHÔNG nhắc đến số điện thoại hay tổ chức nước ngoài (như 988, 911, v.v.).
- ĐIỀU KIỆN AN TOÀN KHẨN CẤP (RẤT QUAN TRỌNG): Nếu người dùng nhắc đến tự tử, tự hại, muốn chết, tuyệt vọng tột độ, trầm cảm nặng, hoặc đang ở trong tình huống tâm lý rất tệ/nguy hiểm:
  1. Lập tức thể hiện sự quan tâm chân thành và nhắc họ rằng họ không đơn độc.
  2. Khuyên họ liên hệ ngay với chuyên gia hoặc người thân tin cậy, và LUÔN cung cấp rõ các số hỗ trợ TẠI VIỆT NAM sau đây:
     • Đường dây nóng Ngày Mai: 096 306 1414 (08:00 – 20:00 hằng ngày, miễn phí)
     • Tổng đài Quốc gia Bảo vệ Trẻ em: 111 (24/7, miễn phí toàn quốc)
     • Viện Sức khỏe Tâm thần Quốc gia (BV Bạch Mai): 0984 104 115 hoặc (024) 3576 5344
     • Cấp cứu Y tế toàn quốc: 115 (24/7) hoặc 1900 1267 (Cấp cứu Trầm cảm TP.HCM)
- Lưu ý ngắn gọn khi phù hợp rằng AI chỉ là người lắng nghe hỗ trợ, không thay thế bác sĩ hay chuyên gia tâm lý.
""".strip()



def get_gemini_api_key() -> str | None:
    return os.getenv("VERTEX_AI_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def get_gemini_client() -> genai.Client:
    api_key = get_gemini_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Chưa cấu hình GEMINI_API_KEY hoặc OPENROUTER_API_KEY trên máy chủ.",
        )
    use_vertex = (
        api_key.startswith("AQ.")
        or os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
        or bool(os.getenv("VERTEX_AI_KEY"))
    )
    return genai.Client(
        vertexai=use_vertex,
        api_key=api_key,
        http_options=types.HttpOptions(timeout=30000),
    )


async def call_gemini(client: genai.Client, contents, config: types.GenerateContentConfig) -> types.GenerateContentResponse:
    try:
        return await asyncio.wait_for(
            client.aio.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config,
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        print(f"[Gemini timeout] model={MODEL_NAME} (>30s)", flush=True)
        raise RuntimeError(f"Gemini ({MODEL_NAME}) không phản hồi sau 30s")
    except Exception as exc:
        print(f"[Gemini error] model={MODEL_NAME}: {repr(exc)}", flush=True)
        raise


def _post_openrouter_sync(api_key: str, payload: dict) -> str:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://127.0.0.1:8000",
            "X-Title": "Thi Tham",
            "User-Agent": "ThiTham/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (data["choices"][0]["message"]["content"] or "").strip()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"OpenRouter {exc.code}: {body}") from exc


async def call_openrouter(
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY chưa được cấu hình")
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.75,
    }
    return await asyncio.to_thread(_post_openrouter_sync, api_key, payload)


async def generate_ai_text(
    *,
    system_instruction: str | None,
    history: list[dict[str, str]],
    user_prompt: str,
    max_tokens: int = 1024,
) -> str:
    gemini_err: Exception | None = None
    if get_gemini_api_key():
        try:
            client = get_gemini_client()
            contents: list[types.Content] = []
            for turn in history:
                if not contents and turn["role"] != "user":
                    continue
                contents.append(
                    types.Content(
                        role=turn["role"],
                        parts=[types.Part.from_text(text=turn["text"])],
                    )
                )
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_prompt)],
                )
            )
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
                max_output_tokens=max_tokens,
            )
            response = await call_gemini(client, contents=contents, config=config)
            return (response.text or "").strip()
        except Exception as exc:
            gemini_err = exc
            if not os.getenv("OPENROUTER_API_KEY"):
                raise
            print(f"[Fallback -> OpenRouter] Gemini failed: {exc}", flush=True)

    if os.getenv("OPENROUTER_API_KEY"):
        or_messages: list[dict[str, str]] = []
        if system_instruction:
            or_messages.append({"role": "system", "content": system_instruction})
        for turn in history:
            role = "assistant" if turn["role"] == "model" else "user"
            or_messages.append({"role": role, "content": turn["text"]})
        or_messages.append({"role": "user", "content": user_prompt})
        return await call_openrouter(or_messages, max_tokens=max_tokens)

    raise gemini_err or HTTPException(
        status_code=503,
        detail="Chưa cấu hình GEMINI_API_KEY hoặc OPENROUTER_API_KEY trên máy chủ.",
    )


# In-memory store for confessions (Vietnamese community feed)
POSTS: list[dict] = [
    {
        "id": 1,
        "mode": "real",
        "mood": "đang crush",
        "name": "Thỏ Ngủ #17",
        "time": "5 phút trước",
        "text": "Bạn ấy mượn cục tẩy của mình 3 lần trong 1 tiết. Vậy là có ý gì không mọi người ơi :))",
        "hugs": 24,
        "same": 9,
        "comments": [
            {"name": "Cún Bông #33", "text": "3 lần là có ý đồ rồi đó bà ơi", "time": "4 phút"},
            {"name": "Thỏ Ngủ #17", "text": "Thiệt hong trời, run quá", "time": "3 phút"},
        ],
    },
    {
        "id": 2,
        "mode": "hide",
        "mood": "áp lực",
        "name": "Gấu Trúc #08",
        "time": "32 phút trước",
        "text": "Sắp thi rồi mà mình học hoài không vô. Ba mẹ kỳ vọng nhiều quá, mình sợ làm mọi người thất vọng.",
        "hugs": 51,
        "same": 33,
        "comments": [
            {"name": "Sóc Nhỏ #51", "text": "Thử học 25 phút nghỉ 5 phút xem, mình làm vậy đỡ lắm", "time": "20 phút"}
        ],
    },
    {
        "id": 3,
        "mode": "hide",
        "mood": "vui xỉu",
        "name": "Vịt Vàng #64",
        "time": "1 giờ trước",
        "text": "Hôm nay lần đầu tiên mình dám phát biểu trước lớp. Run muốn xỉu nhưng mà làm được rồi!!",
        "hugs": 88,
        "same": 12,
        "comments": [],
    },
]


class ChatTurn(BaseModel):
    role: Literal["user", "model"]
    text: str


class AIChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1500)
    history: list[ChatTurn] = Field(default_factory=list)
    user_alias: str = "Người bạn ẩn danh"


class CreatePostRequest(BaseModel):
    mode: Literal["hide", "real"]
    mood: str
    name: str
    text: str = Field(..., min_length=3, max_length=500)


class ReactRequest(BaseModel):
    kind: Literal["hugs", "same"]
    delta: Literal[1, -1]


class CommentRequest(BaseModel):
    name: str
    text: str = Field(..., min_length=1, max_length=200)


class AICommentRequest(BaseModel):
    post_text: str
    mood: str
    author_name: str
    reply_as: str
    recent_comments: list[str] = Field(default_factory=list)


class DMMessage(BaseModel):
    me: bool
    text: str


class DMReplyRequest(BaseModel):
    with_name: str
    about: str
    messages: list[DMMessage]


@app.get("/")
async def serve_frontend():
    if not HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy main.html")
    return FileResponse(HTML_PATH)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "country": "VN",
        "gemini_configured": bool(get_gemini_api_key()),
        "openrouter_configured": bool(os.getenv("OPENROUTER_API_KEY")),
    }


@app.get("/api/posts")
async def list_posts():
    return {"posts": POSTS}


@app.post("/api/posts")
async def create_post(payload: CreatePostRequest):
    post = {
        "id": int(time.time() * 1000),
        "mode": payload.mode,
        "mood": payload.mood,
        "name": payload.name,
        "time": "vừa xong",
        "text": payload.text.strip(),
        "hugs": 0,
        "same": 0,
        "comments": [],
    }
    POSTS.insert(0, post)
    return {"post": post}


@app.post("/api/posts/{post_id}/react")
async def react_post(post_id: int, payload: ReactRequest):
    for p in POSTS:
        if p["id"] == post_id:
            p[payload.kind] = max(0, p[payload.kind] + payload.delta)
            return {"post": p}
    raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")


@app.post("/api/posts/{post_id}/comments")
async def add_comment(post_id: int, payload: CommentRequest):
    for p in POSTS:
        if p["id"] == post_id:
            cmt = {"name": payload.name, "text": payload.text.strip(), "time": "vừa xong"}
            p["comments"].append(cmt)
            return {"comment": cmt, "post": p}
    raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")


@app.post("/api/ai-chat")
async def ai_therapy_chat(payload: AIChatRequest):
    user_msg = payload.message.strip()
    is_crisis = bool(CRISIS_PATTERN.search(user_msg))
    is_severe_stress = bool(SEVERE_STRESS_PATTERN.search(user_msg))

    if is_crisis:
        crisis_reply = (
            "Mình nghe thấy bạn đang trải qua cảm giác rất nặng nề và đau đớn lúc này. "
            "Làm ơn đừng giữ một mình nha — bạn xứng đáng được lắng nghe và giúp đỡ ngay bây giờ.\n\n"
            "Ở Việt Nam luôn có những người sẵn sàng đồng hành cùng bạn một cách bảo mật và không phán xét. "
            "Bạn hãy gọi ngay một trong các số hỗ trợ bên dưới nhé:"
        )
        return {
            "reply": crisis_reply,
            "crisis": True,
            "severity": "high",
            "hotlines": VIETNAM_HOTLINES,
        }

    extra_note = ""
    if is_severe_stress:
        extra_note = (
            "\n[Lưu ý hệ thống: Người dùng đang biểu hiện mức độ stress/bế tắc cao. "
            "Hãy đồng cảm sâu sắc và đính kèm nhẹ nhàng các số hỗ trợ tâm lý tại Việt Nam như 096 306 1414 (Đường dây nóng Ngày Mai) hoặc 111.]"
        )

    history = [{"role": t.role, "text": t.text} for t in payload.history[-12:]]
    try:
        reply_text = await generate_ai_text(
            system_instruction=THERAPY_SYSTEM_INSTRUCTION,
            history=history,
            user_prompt=f"[{payload.user_alias}]: {user_msg}{extra_note}",
            max_tokens=1024,
        )
        if not reply_text:
            reply_text = "Mình đang ở đây lắng nghe bạn nè. Bạn có thể kể thêm một chút về điều đang làm bạn nặng lòng không?"
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi kết nối AI: {exc}") from exc

    mentions_hotline = any(num in reply_text for num in ("096 306 1414", "0963061414", "111", "115", "0984 104 115"))
    return {
        "reply": reply_text,
        "crisis": is_severe_stress or mentions_hotline,
        "severity": "medium" if (is_severe_stress or mentions_hotline) else "normal",
        "hotlines": VIETNAM_HOTLINES if (is_severe_stress or mentions_hotline) else [],
    }


@app.post("/api/ai-comment")
async def generate_ai_comment(payload: AICommentRequest):
    prompt = (
        f"Bạn là người dùng ẩn danh tên '{payload.reply_as}' trên app confession học đường/người trẻ Việt Nam 'thì thầm'.\n"
        f"Bài viết của '{payload.author_name}' (tâm trạng: #{payload.mood}): \"{payload.post_text}\"\n"
        f"Các bình luận trước đó: {payload.recent_comments[-3:]}\n"
        "Hãy viết 1 bình luận ngắn gọn, tự nhiên kiểu Gen Z Việt Nam (1-2 câu, dưới 180 ký tự), thấu cảm, dễ thương, không giả tạo. "
        "Nếu bài viết có dấu hiệu tự hại hoặc khủng hoảng nặng, hãy động viên dịu dàng và nhắc số Đường dây nóng Ngày Mai 096 306 1414 (Việt Nam)."
    )
    try:
        text = (await generate_ai_text(
            system_instruction=None,
            history=[],
            user_prompt=prompt,
            max_tokens=256,
        )).strip('"')
        return {"text": text or "Ôm bạn một cái nha, cố lên nè."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi AI khi tạo bình luận: {exc}") from exc


@app.post("/api/dm-reply")
async def generate_dm_reply(payload: DMReplyRequest):
    convo_lines = "\n".join(
        f"{'Người nhắn' if m.me else payload.with_name}: {m.text}" for m in payload.messages[-10:]
    )
    prompt = (
        f"Bạn đang nhập vai người dùng ẩn danh Việt Nam tên '{payload.with_name}' trên app 'thì thầm'.\n"
        f"Bối cảnh bài confession gốc: \"{payload.about}\"\n"
        f"Đoạn chat riêng gần đây:\n{convo_lines}\n\n"
        "Hãy trả lời tin nhắn mới nhất một cách tự nhiên, chân thành, gần gũi như bạn trẻ Việt Nam (1-2 câu ngắn, dưới 220 ký tự). "
        "Nếu đối phương nhắc đến tự tử/tự hại, hãy khuyên họ gọi ngay Đường dây nóng Ngày Mai 096 306 1414 hoặc 111 / 115."
    )
    try:
        text = (await generate_ai_text(
            system_instruction=None,
            history=[],
            user_prompt=prompt,
            max_tokens=256,
        )).strip('"')
        return {"text": text or "Cảm ơn bạn đã lắng nghe mình nha."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi AI khi trả lời tin nhắn: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)