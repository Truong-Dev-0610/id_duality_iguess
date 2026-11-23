import re

from .base import AIResult, Provider


class MockProvider(Provider):
    """Chạy offline, không cần khóa: dùng để phát triển, kiểm thử và làm phương án cuối khi các AI đều lỗi."""

    kind = "mock"

    @property
    def configured(self):
        return True

    def generate(self, system, messages, temperature=0.6, max_tokens=500):
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        reply = (
            "Mình nghe bạn rồi. Điều bạn chia sẻ nghe có vẻ khiến bạn khá nặng lòng, và cảm xúc đó hoàn toàn đáng được lắng nghe. "
        )
        m = re.search(r"<tai_lieu>\s*\[1\][^\n]*\n(.+?)(?:\n\n|</tai_lieu>)", system, re.S)
        if m:
            sent = re.split(r"(?<=[.!?])\s+", m.group(1).strip())
            reply += "Có một gợi ý có thể thử: " + " ".join(sent[:2]) + " "
        reply += "Bạn kể thêm cho mình về điều khiến bạn bận tâm nhất lúc này nhé?"
        return AIResult(reply, "mock-v1", self.name, 1)
