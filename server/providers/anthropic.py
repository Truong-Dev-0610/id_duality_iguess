import time

import requests

from .base import AIResult, Provider, ProviderError, merge_turns, safe_err


class AnthropicProvider(Provider):
    kind = "anthropic"

    def generate(self, system, messages, temperature=0.6, max_tokens=500):
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": merge_turns(messages),
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        t0 = time.time()
        try:
            r = requests.post(f"{self.base_url}/messages", json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}") from None
        if r.status_code != 200:
            raise ProviderError(f"{self.name}: {safe_err(r)}")
        try:
            text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
        except (ValueError, AttributeError):
            raise ProviderError(f"{self.name}: unexpected response") from None
        if not text:
            raise ProviderError(f"{self.name}: empty response")
        return AIResult(text, self.model, self.name, int((time.time() - t0) * 1000))
