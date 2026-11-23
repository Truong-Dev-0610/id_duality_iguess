import time

import requests

from .base import AIResult, Provider, ProviderError, merge_turns, safe_err


class OpenAICompatProvider(Provider):
    """Dùng cho OpenAI, Groq, OpenRouter, Ollama, LM Studio, vLLM… (giao thức chat/completions)."""

    kind = "openai"

    def generate(self, system, messages, temperature=0.6, max_tokens=500):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + merge_turns(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        t0 = time.time()
        try:
            r = requests.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}") from None
        if r.status_code != 200:
            raise ProviderError(f"{self.name}: {safe_err(r)}")
        try:
            text = (r.json()["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, ValueError, TypeError):
            raise ProviderError(f"{self.name}: unexpected response") from None
        if not text:
            raise ProviderError(f"{self.name}: empty response")
        return AIResult(text, self.model, self.name, int((time.time() - t0) * 1000))
