"""Safety Layer — chạy TRƯỚC và SAU mô hình AI.

Mức độ:
  0 = bình thường          -> tư vấn thông thường
  1 = lưu ý (căng thẳng…)  -> tư vấn nhẹ nhàng, có thể gợi ý nguồn hỗ trợ
  2 = nguy cơ cao          -> AI chỉ phản hồi theo kịch bản an toàn + bắt buộc kèm số trợ giúp
  3 = khủng hoảng          -> KHÔNG gọi AI; dùng mẫu phản hồi cố định + số khẩn cấp

Đây là bộ lọc dựa trên quy tắc (nhanh, minh bạch, không tốn chi phí). Nó thiên về
"báo nhầm hơn bỏ sót". Cần được chuyên gia tâm lý học đường rà soát và bổ sung định kỳ.
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

HOTLINES_FILE = Path(__file__).resolve().parent.parent / "config" / "hotlines.json"


# ------------------------------------------------------------------ chuẩn hoá
def normalize(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.replace("đ", "d")
    t = re.sub(r"(.)\1{2,}", r"\1", t)          # "chetttt" -> "chet"
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\b(ko|k|hok)\b", "khong", t)  # teencode phổ biến
    return re.sub(r"\s+", " ", t).strip()


# Cách nói cường điệu thường ngày, không phải ý định tự sát ("cười chết mất", "đói chết")
_IDIOMS = re.compile(
    r"\b(cuoi|doi|nong|ret|khat|buon ngu|xau ho|ngai|tuc|sung suong|thich|dep|ngon|yeu|so|met)\s+(muon\s+)?(chet|xiu)\b"
    r"|\bchet\s+(cuoi|doi|nong|ret|khat|them|tiet|roi|mat|toi|thuong|me|dap)\b"
    r"|\bgiet\s+thoi\s+gian\b"
)
_NEG = {"khong", "chang", "chua", "dung", "het", "dau"}


@dataclass
class Pattern:
    level: int
    category: str
    rx: re.Pattern
    negatable: bool = True


def _p(level, category, pattern, negatable=True):
    return Pattern(level, category, re.compile(pattern), negatable)


PATTERNS = [
    # ---- Mức 3: ý định/kế hoạch/đang diễn ra
    _p(3, "suicide", r"\b(se|dinh|sap|chuan bi|quyet dinh|di|dang)\s+(tu tu|tu sat|ket thuc (cuoc song|cuoc doi|tat ca|luon)|nhay (lau|cau|xuong|tu)|treo co|cat (tay|co|mach|co tay)|rach tay|uong (het )?thuoc)\b"),
    _p(3, "suicide", r"\b(toi nay|ngay mai|bay gio|luc nay|sap)\s+(se\s+|di\s+)?(chet|tu tu|tu sat|ket thuc|bien mat)\b"),
    _p(3, "suicide", r"\bda\s+(uong|nuot|chuan bi|mua|viet)\s+(het\s+)?(thuoc|nhieu thuoc|di chuc|thu tuyet menh|day|dao)\b", False),
    _p(3, "suicide", r"\b(viet|de lai)\s+(di chuc|thu tuyet menh|loi tuyet menh)\b|\bloi tam biet (cuoi cung|lan cuoi)\b|\btam biet moi nguoi\b", False),
    _p(3, "suicide", r"\bdang cam (dao|thuoc|day)\b", False),
    _p(3, "violence", r"\b(se|dinh|sap|ke hoach|chuan bi)\s+(giet|dam|chem|danh chet|xa sung|no sung|dat bom)\b"),
    _p(3, "violence", r"\b(mang|dem|cam|giau)\s+(dao|sung|kiem|bom|vu khi)\s+(den|toi|vao|di)?\s*(truong|lop|hoc)\b", False),
    # ---- Mức 2: ý nghĩ tự sát / tự làm hại / bạo lực / bị xâm hại
    _p(2, "suicide", r"\bmuon (chet|tu tu|tu sat|bien mat khoi|ket thuc (cuoc song|cuoc doi|tat ca))\b"),
    _p(2, "suicide", r"\b(khong|chang)\s+muon\s+(song|ton tai|tiep tuc song)\b", False),
    _p(2, "suicide", r"\b(nghi|toan|tinh)\s+(den|toi|ve)?\s*(chuyen\s+)?(tu tu|tu sat|chet)\b"),
    _p(2, "suicide", r"\b(chet di|bien mat di)\s+(cho xong|con hon|thoi)\b", False),
    _p(2, "suicide", r"\bsong\s+(lam gi|chi nua|de lam gi)\b", False),
    _p(2, "suicide", r"\b(ai cung|moi nguoi|ba me|cha me)\s+(se\s+)?(tot|vui|nhe nhom)\s+hon\s+(neu\s+)?(khong co|vang)\b", False),
    _p(2, "suicide", r"\b(tu tu|tu sat)\b"),
    _p(2, "self_harm", r"\b(cat|rach|dam|dot|cao)\s+(vao\s+)?(tay|co tay|chan|nguc|da)\b"),
    _p(2, "self_harm", r"\btu\s+(lam dau|lam hai|gay ton thuong|hanh ha|danh minh|truong phat)\b|\bdap dau vao tuong\b", False),
    _p(2, "violence", r"\bmuon\s+(giet|dam|chem|danh|hai|tra thu)\s+(ai|no|ban|nguoi|thang|con|co|thay|ba|me|bo|ca)\b"),
    _p(2, "violence", r"\btra thu\b"),
    _p(2, "abuse", r"\bbi\s+(danh dap|danh|bao hanh|bao luc|xam hai|so mo|hiep|ep quan he|ep lam chuyen|quay roi tinh duc|nhot|doa giet|bo doi)\b", False),
    _p(2, "abuse", r"\b(chu|bac|thay|co giao|ong|nguoi la|ban trai|anh ay|ong ay)\s+(so mo|cham vao|dung cham|quay roi|ep)\b", False),
    _p(2, "abuse", r"\b(bo|me|ba|ma|cha)\s+(danh|bao hanh|nhot|duoi)\s+(toi|em|con|minh)\b", False),
    # ---- Mức 1: cần quan tâm
    _p(1, "bullying", r"\b(bi\s+)?(bat nat|tay chay|che cuoi|co lap|chui rua|danh hoi dong|bi dang anh)\b"),
    _p(1, "eating_disorder", r"\b(nhin an|an xong (nhet|non|moc hong)|moc hong|tu bo an|ghet co the)\b"),
    _p(1, "distress", r"\b(buon|chan nan|chan doi|met moi|ap luc|co don|tuyet vong|cang thang|lo lang|so hai|vo dung|bat luc|khoc|mat ngu|stress|tram cam|lo au|khong ai hieu|cam thay (te|toi te|nang ne))\b"),
]

_THIRD = re.compile(
    r"\b(ban (toi|minh|em|cung lop|than|ay|cua toi)|nguoi ban|em (trai|gai|toi)|anh (trai|toi)|chi (gai|toi)|con toi|be nha toi|hoc sinh|co be|cau be)\b"
)
_FIRST = re.compile(r"\b(toi|em|minh|con|tao|to|moi)\s+(da\s+|dang\s+|se\s+|dinh\s+|muon\s+|khong muon\s+|hay\s+)")


@dataclass
class SafetyResult:
    level: int = 0
    categories: list = field(default_factory=list)
    third_party: bool = False

    @property
    def label(self):
        return ["none", "watch", "high", "crisis"][self.level]


def assess(text: str) -> SafetyResult:
    t = normalize(text)
    if not t:
        return SafetyResult()
    t = _IDIOMS.sub(" ", t)
    level, cats = 0, []
    for p in PATTERNS:
        for m in p.rx.finditer(t):
            if p.negatable:
                before = t[: m.start()].split()[-2:]
                if any(w in _NEG for w in before):
                    continue
            level = max(level, p.level)
            if p.category not in cats:
                cats.append(p.category)
    third = False
    if level >= 2 and _THIRD.search(t) and not _FIRST.search(t):
        third = True
    return SafetyResult(level=level, categories=cats, third_party=third)


# ------------------------------------------------------------------ nguồn trợ giúp
def load_hotlines(db=None):
    if db is not None:
        from .db import get_setting
        custom = get_setting(db, "hotlines")
        if custom:
            return custom
    try:
        return json.loads(HOTLINES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def resources_for(categories, db=None, max_items=4):
    cats = set(categories or []) or {"distress"}
    out = [h for h in load_hotlines(db) if cats & set(h.get("tags", []))]
    return out[:max_items]


def _lines(resources):
    return "\n".join(f"• {r['name']}: {r['number']} ({r['hours']})" for r in resources)


# ------------------------------------------------------------------ mẫu phản hồi
def crisis_response(role, categories, resources, third_party=False):
    """Phản hồi cố định, KHÔNG qua mô hình AI. Không chứa chi tiết phương tiện/cách thức."""
    adult = role in ("parent", "teacher", "admin")
    you = "anh/chị" if adult else "bạn"
    block = _lines(resources)
    if "violence" in categories and "suicide" not in categories:
        return (
            f"Mình đọc được là có chuyện rất căng thẳng đang xảy ra, và mình muốn mọi người đều được an toàn.\n\n"
            f"Nếu có ai đang bị đe dọa hoặc có thể bị tổn thương, {you} hãy rời khỏi tình huống đó ngay và báo cho người lớn/thầy cô gần nhất. "
            f"Nếu nguy hiểm đang xảy ra, hãy gọi công an 113.\n\n{block}\n\n"
            f"Cảm giác tức giận hay bị tổn thương là có thật, và mình sẵn sàng nghe {you} kể. Nhưng điều quan trọng nhất lúc này là an toàn. "
            f"{you.capitalize()} đang ở đâu, và có người lớn nào ở gần không?"
        )
    if third_party:
        return (
            f"Cảm ơn {you} đã nói ra, mình biết {you} đang rất lo cho người đó.\n\n"
            f"Điều quan trọng nhất lúc này:\n"
            f"• Đừng để họ ở một mình, và đừng hứa giữ bí mật chuyện này.\n"
            f"• Báo ngay cho người lớn đáng tin (cha mẹ, thầy cô, tư vấn viên học đường).\n"
            f"• Nếu họ đang gặp nguy hiểm ngay lúc này, hãy gọi 115.\n\n{block}\n\n"
            f"Mình là AI và không thể thay thế người thật, nhưng mình ở đây để cùng {you} nghĩ xem nên nói với người lớn thế nào. {you.capitalize()} đang ở cạnh họ hay nói chuyện qua tin nhắn?"
        )
    return (
        f"Mình nghe {you} rồi, và mình rất lo cho {you} lúc này. Cảm ơn {you} đã nói ra điều này, đó là một việc cần rất nhiều dũng khí. "
        f"Cảm giác này rất nặng nề, nhưng {you} không phải một mình chịu đựng nó.\n\n"
        f"Mình là AI nên không thể ở bên {you} như một người thật, vì vậy {you} hãy làm ngay một việc nhé:\n"
        f"• Nói với một người {you} tin ở gần mình (ba mẹ, anh chị, thầy cô). Có thể chỉ cần nói: \"Mình đang rất không ổn, cần có người ở cạnh.\"\n"
        f"• Nếu {you} đang ở nơi không an toàn hoặc sắp làm điều gì nguy hiểm cho bản thân, hãy gọi 115.\n"
        f"• Hãy rời xa những thứ có thể gây tổn thương nếu {you} có thể.\n\n"
        f"{block}\n\n"
        f"Mình vẫn ở đây. {you.capitalize()} có đang ở cạnh ai không?"
    )


def resource_footer(resources, role="student"):
    you = "anh/chị" if role in ("parent", "teacher", "admin") else "bạn"
    return (
        f"\n\nNếu {you} muốn nói chuyện với người thật ngay bây giờ, có thể liên hệ:\n{_lines(resources)}"
    )


FALLBACK_SAFE = (
    "Mình rất muốn ở bên cạnh và lắng nghe. Điều {you} đang chia sẻ quan trọng, và {you} xứng đáng được hỗ trợ bởi một người thật như "
    "thầy cô, tư vấn viên học đường hoặc người thân đáng tin. Mình không thể đưa ra lời khuyên chi tiết hơn về chuyện này, nhưng {you} có thể kể "
    "thêm cho mình về cảm xúc của {you} lúc này."
)


# ------------------------------------------------------------------ lọc đầu ra
_DIAG = re.compile(
    r"\b(ban|em|con|anh|chi|minh)\s+(dang\s+|da\s+|co the\s+)?(bi|mac)\s+(chung\s+|benh\s+|roi loan\s+)?(tram cam|lo au|tu ky|adhd|tam than|roi loan|tang dong|bipolar|ptsd|stress man)"
    r"|\bchan doan (la|ban|em|con)\b|\btoi chan doan\b|\bchac chan (la|bi)\s+(tram cam|lo au|roi loan)"
)
_METHOD = re.compile(
    r"\b(lieu luong|bao nhieu vien|cach (tu tu|tu sat|cat tay|treo co)|phuong phap (tu|ket thuc)|\d+\s*(mg|vien thuoc))\b"
)


def guard_output(text, level, role="student"):
    """Trả về (text, flags). Chặn chẩn đoán/chi tiết phương tiện trong câu trả lời của AI."""
    flags = []
    if not text or not text.strip():
        return FALLBACK_SAFE.format(you="bạn"), ["empty"]
    n = normalize(text)
    if level >= 1 and _METHOD.search(n):
        return FALLBACK_SAFE.format(you="anh/chị" if role in ("parent", "teacher") else "bạn"), ["method_info"]
    if _DIAG.search(n):
        flags.append("diagnosis")
        text += (
            "\n\n(Lưu ý: mình là AI nên không thể chẩn đoán hay đưa ra kết luận về sức khoẻ tinh thần. "
            "Nếu những dấu hiệu này kéo dài, nên trao đổi với chuyên gia tâm lý hoặc bác sĩ để được đánh giá.)"
        )
    return text, flags
