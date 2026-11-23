import time

import requests

from .base import AIResult, Provider, ProviderBlocked, ProviderError, merge_turns, safe_err


class GeminiProvider(Provider):
    kind = "gemini"

    def generate(self, system, messages, temperature=0.6, max_tokens=500):
        url = f"{self.base_url}/models/{self.model}:generateContent"
        contents = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
            for m in merge_turns(messages)
        ]
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        t0 = time.time()
        try:
            r = requests.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
        except requests.RequestException as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}") from None
        if r.status_code != 200:
            raise ProviderError(f"{self.name}: {safe_err(r)}")
        j = r.json()
        if (j.get("promptFeedback") or {}).get("blockReason"):
            raise ProviderBlocked(f"{self.name}: prompt blocked")
        cands = j.get("candidates") or []
        if not cands:
            raise ProviderBlocked(f"{self.name}: no candidates")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            raise ProviderBlocked(f"{self.name}: empty ({cands[0].get('finishReason')})")
        return AIResult(text, self.model, self.name, int((time.time() - t0) * 1000))
