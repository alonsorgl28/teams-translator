from __future__ import annotations

import os
import re
from typing import Final, Optional

from openai import APIStatusError, AsyncOpenAI, OpenAI


class TechnicalTranslationService:
    _SUPPORTED_LANGS: Final[tuple[str, ...]] = (
        "English",
        "Portuguese (Brazil)",
        "Mandarin Chinese (Simplified)",
        "Hindi",
        "Spanish",
    )

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-5.3") -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for translation.")
        self._client = AsyncOpenAI(api_key=key)
        self._sync_client = OpenAI(api_key=key)
        primary_model = os.getenv("TRANSLATION_MODEL", model).strip() or model
        fallback_model = os.getenv("TRANSLATION_FALLBACK_MODEL", "gpt-4o-mini").strip()
        self._models = [primary_model]
        if fallback_model and fallback_model not in self._models:
            self._models.append(fallback_model)
        self.last_error: Optional[str] = None
        self._protected_terms = [
            "AAAC",
            "ACSR",
            "OPGW",
            "DDP",
            "FOB",
            "CIF",
            "Power transmission",
            "Insulators",
            "Conductors",
            "Electrical tenders",
        ]

    async def translate_text(self, text: str) -> str:
        self.last_error = None
        cleaned = self._sanitize(text)
        if not cleaned:
            return ""
        if self._looks_spanish(cleaned):
            return cleaned

        number_tokens = self._extract_numeric_tokens(cleaned)
        try:
            translated = await self._translate_once(cleaned, number_tokens)
            if self._numbers_preserved(number_tokens, translated):
                return translated

            strict_prompt = (
                "Repair the Spanish translation below. Keep ALL numbers and units exactly as provided, "
                "without formatting changes. Keep technical tone. Return only corrected Spanish text.\n\n"
                f"Source:\n{cleaned}\n\n"
                f"Current translation:\n{translated}\n\n"
                f"Tokens that MUST remain exact: {', '.join(number_tokens) if number_tokens else 'None'}"
            )
            repaired = await self._chat(strict_prompt)
            return repaired if repaired else translated
        except Exception as exc:  # noqa: BLE001 - graceful fallback
            self.last_error = f"translation_failed: {exc}"
            return cleaned

    async def translate_to_spanish(self, source_text: str, source_language: str = "auto") -> str:
        del source_language
        return await self.translate_text(source_text)

    async def _translate_once(self, source_text: str, number_tokens: list[str]) -> str:
        numbers_line = ", ".join(number_tokens) if number_tokens else "None"
        system_prompt = (
            "You are a low-latency technical translation engine for Microsoft Teams meetings.\n"
            "Auto-detect the source language and translate to Spanish.\n"
            "Rules:\n"
            "1) Supported source languages: English, Portuguese (Brazil), Mandarin Chinese (Simplified), Hindi.\n"
            "2) If input is already Spanish, return it unchanged.\n"
            "3) Preserve technical terms when needed: AAAC, ACSR, OPGW, DDP, FOB, CIF.\n"
            "4) Never alter numbers, decimals, units, identifiers, model numbers, or percentages.\n"
            "5) Avoid hallucinations. Keep output concise, natural, and technically accurate.\n"
            "6) Never answer, explain, or refuse; only translate the provided text.\n"
            "7) Return clean Spanish text only, with no commentary."
        )
        user_prompt = (
            f"Supported language set: {', '.join(self._SUPPORTED_LANGS)}\n"
            f"Number/unit tokens to preserve exactly: {numbers_line}\n"
            f"Protected domain terms: {', '.join(self._protected_terms)}\n\n"
            f"Text:\n{source_text}"
        )
        return await self._chat(user_prompt, system_prompt)

    async def _chat(self, user_prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        last_exc: Optional[Exception] = None
        for model_name in self._models:
            try:
                response = await self._client.chat.completions.create(
                    model=model_name,
                    temperature=0.2,
                    messages=messages,
                )
                content = response.choices[0].message.content or ""
                return self._sanitize(content)
            except APIStatusError as exc:
                last_exc = exc
                # Retry with fallback model when model is unavailable or unsupported.
                if exc.status_code in (400, 404):
                    continue
                raise
            except Exception as exc:  # noqa: BLE001 - API boundary
                last_exc = exc
                break
        raise RuntimeError(f"Translation API failed with all configured models: {last_exc}") from last_exc

    @staticmethod
    def _extract_numeric_tokens(text: str) -> list[str]:
        pattern = re.compile(
            r"(?<!\w)"
            r"[+-]?\d+(?:[.,]\d+)?"
            r"(?:\s?(?:kV|V|kA|A|MW|MVA|Hz|mm2|mm²|cm|mm|m|km|kg|t|%|°C))?"
            r"(?!\w)"
        )
        return pattern.findall(text)

    @staticmethod
    def _numbers_preserved(tokens: list[str], translation: str) -> bool:
        for token in tokens:
            if token not in translation:
                return False
        return True

    @staticmethod
    def _sanitize(text: str) -> str:
        collapsed = re.sub(r"\s+", " ", text or "").strip()
        return collapsed

    @staticmethod
    def _looks_spanish(text: str) -> bool:
        lowered = f" {text.lower()} "
        hit_count = 0
        markers = (
            " el ",
            " la ",
            " de ",
            " y ",
            " en ",
            " para ",
            " con ",
            " los ",
            " las ",
            " del ",
            " una ",
            " un ",
        )
        for marker in markers:
            if marker in lowered:
                hit_count += 1
        return hit_count >= 2


def translate_text(text: str) -> str:
    cleaned = TechnicalTranslationService._sanitize(text)
    if not cleaned:
        return ""
    if TechnicalTranslationService._looks_spanish(cleaned):
        return cleaned

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return cleaned

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("TRANSLATION_MODEL", "gpt-5.3"),
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Auto-detect source language and translate to Spanish only. "
                        "If already Spanish, return unchanged. Keep concise, natural, and accurate."
                    ),
                },
                {"role": "user", "content": cleaned},
            ],
        )
        output = (response.choices[0].message.content or "").strip()
        return TechnicalTranslationService._sanitize(output) or cleaned
    except Exception:  # noqa: BLE001 - graceful fallback
        return cleaned
