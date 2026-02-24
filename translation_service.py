from __future__ import annotations

import os
import re
from collections import deque
from typing import Final, Optional

from openai import APIStatusError, AsyncOpenAI

from config_utils import read_bool_env, read_int_env


class TechnicalTranslationService:
    SPANISH_MARKER_MIN_HITS: Final[int] = 4
    _SUPPORTED_LANGS: Final[tuple[str, ...]] = (
        "English",
        "Portuguese (Brazil)",
        "Mandarin Chinese (Simplified)",
        "Hindi",
        "Spanish",
    )
    _COMMON_WORDS: Final[set[str]] = {
        "the",
        "this",
        "that",
        "with",
        "from",
        "about",
        "there",
        "would",
        "could",
        "should",
        "because",
        "really",
        "where",
        "which",
        "while",
        "como",
        "para",
        "pero",
        "esto",
        "esta",
        "este",
        "muy",
        "más",
        "menos",
        "porque",
        "también",
        "entonces",
        "cuando",
        "sobre",
        "entre",
        "modelos",
        "código",
    }

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini") -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for translation.")
        self._client = AsyncOpenAI(api_key=key)
        primary_model = os.getenv("TRANSLATION_MODEL", model).strip() or model
        fallback_model = os.getenv("TRANSLATION_FALLBACK_MODEL", "gpt-4.1-mini").strip()
        self._models = [primary_model]
        if fallback_model and fallback_model not in self._models:
            self._models.append(fallback_model)
        self._active_model_index = 0
        self._max_completion_tokens = read_int_env("TRANSLATION_MAX_TOKENS", 120)
        self.last_error: Optional[str] = None
        raw_terms = (os.getenv("PROTECTED_TERMS") or "").strip()
        self._protected_terms = [term.strip() for term in raw_terms.split(",") if term.strip()]
        turns = read_int_env("TRANSLATION_CONTEXT_TURNS", 6)
        self._recent_source: deque[str] = deque(maxlen=turns)
        self._recent_translations: deque[str] = deque(maxlen=turns)
        self._context_enabled = read_bool_env("TRANSLATION_CONTEXT_ENABLED", True)
        self._context_max_chars = read_int_env("TRANSLATION_CONTEXT_MAX_CHARS", 220)
        self._glossary_enabled = read_bool_env("TRANSLATION_GLOSSARY_ENABLED", True)
        self._session_terms: dict[str, int] = {}
        self._term_memory_size = read_int_env("TERM_MEMORY_SIZE", 24)
        self._term_min_count = read_int_env("TERM_MIN_COUNT", 2)

    async def translate_text(self, text: str, target_language: str = "Spanish") -> str:
        self.last_error = None
        cleaned = self._sanitize(text)
        if not cleaned:
            return ""
        normalized_target = self._normalize_target_language(target_language)
        if normalized_target.lower() == "spanish" and self._looks_spanish(cleaned):
            return cleaned

        number_tokens = self._extract_numeric_tokens(cleaned)
        recent_source_context = self._context_block(self._recent_source)
        recent_translation_context = self._context_block(self._recent_translations)
        session_terms = self._session_glossary_text()
        try:
            translated = await self._translate_once(
                cleaned,
                number_tokens,
                target_language=normalized_target,
                recent_source_context=recent_source_context,
                recent_translation_context=recent_translation_context,
                session_terms=session_terms,
            )
            if self._is_refusal_like(translated):
                retry = await self._translate_literal(
                    cleaned,
                    number_tokens,
                    target_language=normalized_target,
                    recent_source_context=recent_source_context,
                    session_terms=session_terms,
                )
                if retry and not self._is_refusal_like(retry):
                    translated = retry
                else:
                    self.last_error = "translation_refusal_fallback_source"
                    return cleaned
            if self._numbers_preserved(number_tokens, translated):
                normalized_output = (
                    self._repair_spanish_residual_english(translated)
                    if normalized_target.lower() == "spanish"
                    else translated
                )
                self._remember_turn(cleaned, normalized_output)
                return normalized_output

            strict_prompt = (
                "Repair the Spanish translation below. Keep ALL numbers and units exactly as provided, "
                "without formatting changes. Keep technical tone. Return only corrected Spanish text.\n\n"
                f"Source:\n{cleaned}\n\n"
                f"Current translation:\n{translated}\n\n"
                f"Tokens that MUST remain exact: {', '.join(number_tokens) if number_tokens else 'None'}"
            )
            if normalized_target.lower() != "spanish":
                strict_prompt = (
                    "Repair the translation below. Keep ALL numbers and units exactly as provided, "
                    f"without formatting changes. Keep technical tone in {normalized_target}. "
                    "Return only corrected translated text.\n\n"
                    f"Source:\n{cleaned}\n\n"
                    f"Current translation:\n{translated}\n\n"
                    f"Tokens that MUST remain exact: {', '.join(number_tokens) if number_tokens else 'None'}"
                )
            repaired = await self._chat(strict_prompt)
            if self._is_refusal_like(repaired):
                self.last_error = "translation_refusal_on_repair"
                fallback = translated or cleaned
                if normalized_target.lower() == "spanish":
                    return self._repair_spanish_residual_english(fallback)
                return fallback
            final_translation = repaired if repaired else translated
            if normalized_target.lower() == "spanish":
                final_translation = self._repair_spanish_residual_english(final_translation)
            self._remember_turn(cleaned, final_translation)
            return final_translation
        except Exception as exc:  # noqa: BLE001 - graceful fallback
            self.last_error = f"translation_failed: {exc}"
            return cleaned

    async def _translate_once(
        self,
        source_text: str,
        number_tokens: list[str],
        target_language: str,
        recent_source_context: str,
        recent_translation_context: str,
        session_terms: str,
    ) -> str:
        numbers_line = ", ".join(number_tokens) if number_tokens else "None"
        system_prompt = (
            "You are a real-time transcript translator for meetings.\n"
            f"Translate the input fragment into neutral {target_language}.\n"
            "Rules:\n"
            f"1) If input is already {target_language}, return it unchanged.\n"
            "2) Keep proper names, acronyms, numbers, units, and identifiers exactly when present.\n"
            "3) Keep the same level of certainty and tone. Do not summarize, shorten, or paraphrase away details.\n"
            "4) This is transformation only. Never refuse, apologize, explain, or add safety disclaimers.\n"
            "5) Translate common words and pronouns (for example: you, we, they, model); preserve only true names/brands.\n"
            "6) Use context only to disambiguate terms. Do not invent facts, words, or sentences not in source.\n"
            "7) Prefer subtitle-like natural phrasing, but keep meaning and technical terms exact.\n"
            "8) Return only the translated text."
        )
        prompt_lines = [
            f"Supported language set: {', '.join(self._SUPPORTED_LANGS)}",
            f"Target language: {target_language}",
            f"Number/unit tokens to preserve exactly: {numbers_line}",
            f"Protected terms from env: {', '.join(self._protected_terms) if self._protected_terms else 'None'}",
        ]
        if session_terms:
            prompt_lines.append(f"Session glossary (keep when appropriate): {session_terms}")
        if recent_source_context:
            prompt_lines.append(f"Recent source context:\n{recent_source_context}")
        if recent_translation_context:
            prompt_lines.append(f"Recent Spanish context:\n{recent_translation_context}")
        prompt_lines.append(f"Text:\n{source_text}")
        user_prompt = "\n\n".join(prompt_lines)
        return await self._chat(user_prompt, system_prompt)

    async def _translate_literal(
        self,
        source_text: str,
        number_tokens: list[str],
        target_language: str,
        recent_source_context: str,
        session_terms: str,
    ) -> str:
        numbers_line = ", ".join(number_tokens) if number_tokens else "None"
        system_prompt = (
            f"Translate the transcript fragment to {target_language} literally.\n"
            "Do not refuse, do not explain, and do not add any extra text.\n"
            "Use context only for terminology disambiguation; do not add unseen content.\n"
            f"Return only translated {target_language}."
        )
        prompt_lines = [
            f"Target language: {target_language}",
            f"Keep these tokens exact if they appear: {numbers_line}",
        ]
        if session_terms:
            prompt_lines.append(f"Session glossary: {session_terms}")
        if recent_source_context:
            prompt_lines.append(f"Recent source context:\n{recent_source_context}")
        prompt_lines.append(f"Text:\n{source_text}")
        user_prompt = "\n\n".join(prompt_lines)
        return await self._chat(user_prompt, system_prompt)

    @staticmethod
    def _normalize_target_language(target_language: str) -> str:
        raw = (target_language or "").strip()
        if not raw:
            return "Spanish"
        aliases = {
            "es": "Spanish",
            "en": "English",
            "pt": "Portuguese (Brazil)",
            "pt-br": "Portuguese (Brazil)",
            "zh": "Mandarin Chinese (Simplified)",
            "zh-cn": "Mandarin Chinese (Simplified)",
            "hi": "Hindi",
        }
        lowered = raw.lower()
        return aliases.get(lowered, raw)

    @staticmethod
    def _repair_spanish_residual_english(text: str) -> str:
        if not text:
            return text
        repaired = text
        substitutions = (
            (r"\bYou\b(?!Tube)", "tú"),
            (r"\bmodel\b", "modelo"),
            (r"\bmodels\b", "modelos"),
            (r"\bwith\b", "con"),
            (r"\band\b", "y"),
            (r"\bcode\b", "código"),
        )
        for pattern, replacement in substitutions:
            repaired = re.sub(pattern, replacement, repaired, flags=re.IGNORECASE)
        repaired = re.sub(r"\s+", " ", repaired).strip()
        return repaired

    async def _chat(self, user_prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        last_exc: Optional[Exception] = None
        while self._active_model_index < len(self._models):
            model_name = self._models[self._active_model_index]
            try:
                response = await self._client.chat.completions.create(
                    model=model_name,
                    temperature=0.0,
                    messages=messages,
                    max_tokens=self._max_completion_tokens,
                )
                content = response.choices[0].message.content or ""
                return self._sanitize(content)
            except APIStatusError as exc:
                last_exc = exc
                # Promote to fallback model once and keep it for subsequent requests.
                if exc.status_code in (400, 404):
                    self._active_model_index += 1
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
        return hit_count >= TechnicalTranslationService.SPANISH_MARKER_MIN_HITS

    @staticmethod
    def _is_refusal_like(text: str) -> bool:
        normalized = TechnicalTranslationService._sanitize(text).lower()
        if not normalized:
            return False
        refusal_patterns = (
            "lo siento, no puedo ayudar con eso",
            "lo siento, no puedo ayudarte con eso",
            "no puedo ayudar con eso",
            "i'm sorry, i can't help with that",
            "i cannot help with that",
            "i can\u2019t help with that",
            "i can't assist with that",
            "cannot assist with that",
        )
        return any(pattern in normalized for pattern in refusal_patterns)

    @staticmethod
    def _extract_candidate_terms(text: str) -> list[str]:
        candidates: set[str] = set()
        for token in re.findall(r"\b[A-Za-z]*\d[\w.-]*\b", text):
            candidates.add(token)
        for token in re.findall(r"\b[A-Z]{2,}(?:[.-][A-Z0-9]+)*\b", text):
            candidates.add(token)
        for phrase in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", text):
            candidates.add(phrase)
        return list(candidates)

    def _remember_turn(self, source_text: str, translated_text: str) -> None:
        if self._context_enabled:
            self._recent_source.append(source_text)
            self._recent_translations.append(translated_text)
        if not self._glossary_enabled:
            return
        for term in self._extract_candidate_terms(source_text):
            self._session_terms[term] = self._session_terms.get(term, 0) + 1
        for token in re.findall(r"\b[a-zA-Z][a-zA-Z0-9.-]{3,}\b", source_text):
            lowered = token.lower()
            if lowered in self._COMMON_WORDS:
                continue
            self._session_terms[lowered] = self._session_terms.get(lowered, 0) + 1
        if len(self._session_terms) > self._term_memory_size:
            # Keep most frequent learned terms only.
            sorted_terms = sorted(self._session_terms.items(), key=lambda item: item[1], reverse=True)
            self._session_terms = dict(sorted_terms[: self._term_memory_size])

    def _session_glossary_text(self) -> str:
        if not self._glossary_enabled:
            return ""
        if not self._session_terms:
            return ""
        stable_terms = [
            term
            for term, count in sorted(self._session_terms.items(), key=lambda item: item[1], reverse=True)
            if count >= self._term_min_count
        ]
        return ", ".join(stable_terms[: self._term_memory_size])

    def _context_block(self, items: deque[str]) -> str:
        if not self._context_enabled:
            return ""
        if not items:
            return ""
        merged = "\n".join(items)
        return merged[-self._context_max_chars :]
