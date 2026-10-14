"""Gemini provider. Activated with LLM_BACKEND=gemini + GEMINI_API_KEY.

Nothing here invents credentials: the key is read from the environment and a
clear error is raised if it is missing.
"""
from __future__ import annotations

from typing import Iterator

from django.conf import settings

from .base import LLMProvider


class GeminiLLM(LLMProvider):
    name = "gemini"

    def __init__(self):
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise RuntimeError(
                "google-generativeai is not installed. pip install google-generativeai "
                "or set LLM_BACKEND=fake."
            ) from exc
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise RuntimeError("LLM_BACKEND=gemini requires the GEMINI_API_KEY env var.")
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(settings.GEMINI_MODEL)

    def _contents(self, system: str, user: str) -> str:
        return f"{system}\n\n{user}"

    def generate(self, system: str, user: str, *, max_tokens: int = 512) -> str:
        resp = self._model.generate_content(
            self._contents(system, user),
            generation_config={"max_output_tokens": max_tokens, "temperature": 0.2},
        )
        return resp.text

    def stream(self, system: str, user: str, *, max_tokens: int = 512) -> Iterator[str]:
        resp = self._model.generate_content(
            self._contents(system, user),
            generation_config={"max_output_tokens": max_tokens, "temperature": 0.2},
            stream=True,
        )
        for chunk in resp:
            if chunk.text:
                yield chunk.text

    def estimate_tokens(self, text: str) -> int:
        try:
            return self._model.count_tokens(text).total_tokens
        except Exception:  # noqa: BLE001 - fall back to the rough estimate
            return max(1, len(text) // 4)
