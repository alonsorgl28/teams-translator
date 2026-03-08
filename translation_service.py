from __future__ import annotations

import csv
import difflib
import os
import re
from collections import deque
from pathlib import Path
from typing import Final, Optional

from openai import APIStatusError, AsyncOpenAI

from config_utils import read_bool_env, read_float_env, read_int_env
from segment_quality import TranslationRoute


class TechnicalTranslationService:
    SPANISH_MARKER_MIN_HITS: Final[int] = 4
    _INCOMPLETE_TRAILING_TOKENS: Final[set[str]] = {
        "and",
        "or",
        "but",
        "the",
        "a",
        "an",
        "to",
        "of",
        "for",
        "with",
        "that",
        "than",
        "into",
        "from",
        "about",
        "como",
        "pero",
        "para",
        "con",
        "sin",
        "que",
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "un",
        "una",
    }
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
    _ENGLISH_FUNCTION_WORDS: Final[set[str]] = {
        "the",
        "and",
        "or",
        "with",
        "for",
        "to",
        "of",
        "in",
        "on",
        "is",
        "are",
        "was",
        "were",
        "this",
        "that",
        "it",
        "you",
        "we",
        "they",
        "i",
    }
    _SPANISH_FUNCTION_WORDS: Final[set[str]] = {
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "y",
        "con",
        "para",
        "en",
        "que",
        "es",
        "un",
        "una",
        "por",
        "se",
        "como",
        "pero",
        "muy",
        "más",
        "menos",
        "hola",
        "gracias",
        "sí",
        "no",
        "bueno",
        "buena",
        "buen",
    }
    _TERM_LIKE_TOKENS: Final[set[str]] = {
        "gpt",
        "codex",
        "claude",
        "opus",
        "openai",
        "lex",
        "fridman",
        "youtube",
        "ai",
    }

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini") -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for translation.")
        self._client = AsyncOpenAI(api_key=key)
        primary_model = os.getenv("TRANSLATION_MODEL", model).strip() or model
        fallback_model = os.getenv("TRANSLATION_FALLBACK_MODEL", "gpt-4o-mini").strip()
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
        self._allow_target_passthrough = read_bool_env("ALLOW_TARGET_LANGUAGE_PASSTHROUGH", False)
        self._glossary_enabled = read_bool_env("TRANSLATION_GLOSSARY_ENABLED", True)
        self._session_terms: dict[str, int] = {}
        self._term_memory_size = read_int_env("TERM_MEMORY_SIZE", 24)
        self._term_min_count = read_int_env("TERM_MIN_COUNT", 2)
        glossary_path = (os.getenv("ENERGY_GLOSSARY_PATH") or "").strip()
        self._energy_glossary = self._load_energy_glossary(glossary_path)
        self._energy_glossary_max_rules = read_int_env("ENERGY_GLOSSARY_MAX_RULES", 10)
        if self._energy_glossary:
            for item in self._energy_glossary:
                rule = item.get("rule", "").strip().lower()
                if rule in {"keep_acronym", "keep_term", "map_acronym"}:
                    if item.get("term_en"):
                        self._protected_terms.append(item["term_en"])
                    continue
                if item.get("term_es"):
                    self._protected_terms.append(item["term_es"])
        self._protected_terms = list(dict.fromkeys(term.strip() for term in self._protected_terms if term.strip()))
        self._premium_model = (os.getenv("PREMIUM_TRANSLATION_MODEL") or "gpt-4o").strip()
        self._premium_trigger_score = read_float_env("PREMIUM_TRIGGER_SCORE", 0.82)
        self._premium_max_ratio = max(0.05, min(1.0, read_float_env("PREMIUM_MAX_RATIO", 0.25)))
        self._segments_routed = 0
        self._premium_segments = 0

    @property
    def premium_ratio(self) -> float:
        if self._segments_routed == 0:
            return 0.0
        return self._premium_segments / self._segments_routed

    @property
    def premium_enabled(self) -> bool:
        return bool(self._premium_model)

    def _can_route_premium(self) -> bool:
        return self.premium_ratio < self._premium_max_ratio

    def _select_route(self, confidence_score: float, force_premium: bool) -> TranslationRoute:
        if not self.premium_enabled:
            return "normal"
        if not self._can_route_premium() and not force_premium:
            return "normal"
        if force_premium:
            return "premium"
        if confidence_score < self._premium_trigger_score and self._can_route_premium():
            return "premium"
        return "normal"

    async def translate_text_with_route(
        self,
        text: str,
        *,
        target_language: str = "Spanish",
        confidence_score: float = 1.0,
        force_premium: bool = False,
    ) -> tuple[str, TranslationRoute]:
        route = self._select_route(confidence_score, force_premium)
        self._segments_routed += 1
        if route == "premium":
            self._premium_segments += 1
        model_override = self._premium_model if route == "premium" else None
        translated = await self.translate_text(text, target_language=target_language, model_override=model_override)
        return translated, route

    async def translate_text(
        self,
        text: str,
        target_language: str = "Spanish",
        *,
        model_override: Optional[str] = None,
    ) -> str:
        self.last_error = None
        cleaned = self._sanitize(text)
        if not cleaned:
            return ""
        normalized_target = self._normalize_target_language(target_language)
        if self._allow_target_passthrough and normalized_target.lower() == "spanish" and self._looks_spanish(cleaned):
            return cleaned

        number_tokens = self._extract_numeric_tokens(cleaned)
        use_context = self._should_use_context(cleaned)
        recent_source_context = self._context_block(self._recent_source) if use_context else ""
        recent_translation_context = self._context_block(self._recent_translations) if use_context else ""
        session_terms = self._session_glossary_text()
        domain_glossary = self._matched_domain_glossary(cleaned, normalized_target)
        prefer_literal = self._should_force_literal_translation(cleaned)
        try:
            if prefer_literal:
                translated = await self._translate_literal(
                    cleaned,
                    number_tokens,
                    target_language=normalized_target,
                    recent_source_context="",
                    session_terms="",
                    domain_glossary=domain_glossary,
                    model_override=model_override,
                )
            else:
                translated = await self._translate_once(
                    cleaned,
                    number_tokens,
                    target_language=normalized_target,
                    recent_source_context=recent_source_context,
                    recent_translation_context=recent_translation_context,
                    session_terms=session_terms,
                    domain_glossary=domain_glossary,
                    model_override=model_override,
                )
            if self._is_refusal_like(translated):
                retry = await self._translate_literal(
                    cleaned,
                    number_tokens,
                    target_language=normalized_target,
                    recent_source_context=recent_source_context,
                    session_terms=session_terms,
                    domain_glossary=domain_glossary,
                    model_override=model_override,
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
                normalized_output = self._apply_domain_glossary(
                    source_text=cleaned,
                    translated_text=normalized_output,
                    target_language=normalized_target,
                    domain_glossary=domain_glossary,
                )
                if normalized_target.lower() == "spanish":
                    normalized_output = await self._enforce_spanish_output(
                        source_text=cleaned,
                        current_output=normalized_output,
                        number_tokens=number_tokens,
                        target_language=normalized_target,
                        model_override=model_override,
                    )
                if normalized_target.lower() == "spanish" and self._looks_non_spanish_output(normalized_output):
                    self.last_error = "translation_non_spanish_suppressed"
                    return ""
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
            repaired = await self._chat(strict_prompt, model_override=model_override)
            if self._is_refusal_like(repaired):
                self.last_error = "translation_refusal_on_repair"
                fallback = translated or cleaned
                if normalized_target.lower() == "spanish":
                    return self._repair_spanish_residual_english(fallback)
                return fallback
            final_translation = repaired if repaired else translated
            if normalized_target.lower() == "spanish":
                final_translation = self._repair_spanish_residual_english(final_translation)
                final_translation = self._apply_domain_glossary(
                    source_text=cleaned,
                    translated_text=final_translation,
                    target_language=normalized_target,
                    domain_glossary=domain_glossary,
                )
                final_translation = await self._enforce_spanish_output(
                    source_text=cleaned,
                    current_output=final_translation,
                    number_tokens=number_tokens,
                    target_language=normalized_target,
                    model_override=model_override,
                )
            if normalized_target.lower() == "spanish" and self._looks_non_spanish_output(final_translation):
                self.last_error = "translation_non_spanish_suppressed"
                return ""
            self._remember_turn(cleaned, final_translation)
            return final_translation
        except Exception as exc:  # noqa: BLE001 - graceful fallback
            self.last_error = f"translation_failed: {exc}"
            return cleaned

    async def _enforce_spanish_output(
        self,
        *,
        source_text: str,
        current_output: str,
        number_tokens: list[str],
        target_language: str,
        model_override: Optional[str] = None,
    ) -> str:
        needs_fix = self._looks_non_spanish_output(current_output) or self._looks_too_similar_to_source(
            source_text,
            current_output,
        )
        if not needs_fix:
            return current_output
        retry = await self._translate_literal(
            source_text,
            number_tokens,
            target_language=target_language,
            recent_source_context="",
            session_terms="",
            domain_glossary=[],
            model_override=model_override,
        )
        candidate = retry or current_output
        if self._looks_non_spanish_output(candidate) or self._looks_too_similar_to_source(source_text, candidate):
            return self._repair_spanish_residual_english(candidate)
        return candidate

    async def _translate_once(
        self,
        source_text: str,
        number_tokens: list[str],
        target_language: str,
        recent_source_context: str,
        recent_translation_context: str,
        session_terms: str,
        domain_glossary: list[dict[str, str]],
        model_override: Optional[str] = None,
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
            "7) Translate short fragments literally even if they start mid-sentence.\n"
            "8) Translate pronouns, fillers, and discourse markers unless they are part of a brand/title.\n"
            "9) Prefer direct translation over stylistic paraphrase. Never complete an unfinished thought.\n"
            "10) Return only the translated text."
        )
        prompt_lines = [
            f"Supported language set: {', '.join(self._SUPPORTED_LANGS)}",
            f"Target language: {target_language}",
            f"Number/unit tokens to preserve exactly: {numbers_line}",
            f"Protected terms from env: {', '.join(self._protected_terms) if self._protected_terms else 'None'}",
        ]
        if session_terms:
            prompt_lines.append(f"Session glossary (keep when appropriate): {session_terms}")
        domain_rules = self._domain_glossary_prompt(domain_glossary)
        if domain_rules:
            prompt_lines.append(f"Domain glossary EN->ES (must obey when term appears): {domain_rules}")
        if recent_source_context:
            prompt_lines.append(f"Recent source context:\n{recent_source_context}")
        if recent_translation_context:
            prompt_lines.append(f"Recent Spanish context:\n{recent_translation_context}")
        prompt_lines.append(f"Text:\n{source_text}")
        user_prompt = "\n\n".join(prompt_lines)
        return await self._chat(user_prompt, system_prompt, model_override=model_override)

    async def _translate_literal(
        self,
        source_text: str,
        number_tokens: list[str],
        target_language: str,
        recent_source_context: str,
        session_terms: str,
        domain_glossary: list[dict[str, str]],
        model_override: Optional[str] = None,
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
        domain_rules = self._domain_glossary_prompt(domain_glossary)
        if domain_rules:
            prompt_lines.append(f"Domain glossary EN->ES (must obey when term appears): {domain_rules}")
        if recent_source_context:
            prompt_lines.append(f"Recent source context:\n{recent_source_context}")
        prompt_lines.append(f"Text:\n{source_text}")
        user_prompt = "\n\n".join(prompt_lines)
        return await self._chat(user_prompt, system_prompt, model_override=model_override)

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

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text or ""))

    @staticmethod
    def _contains_non_latin_script(text: str) -> bool:
        return bool(re.search(r"[\u0400-\u052F\u0590-\u05FF\u0600-\u06FF\u0750-\u077F]", text or ""))

    @classmethod
    def _looks_unstable_token_sequence(cls, words: list[str]) -> bool:
        unstable = 0
        for raw in words:
            token = raw.lower()
            if len(token) <= 2:
                continue
            if re.search(r"[bcdfghjklmnñpqrstvwxyz]{5,}", token):
                unstable += 1
                continue
            if len(token) >= 6 and not re.search(r"[aeiouáéíóúü]", token):
                unstable += 1
        return unstable >= max(1, len(words) // 2)

    @classmethod
    def _looks_non_spanish_output(cls, text: str) -> bool:
        cleaned = cls._sanitize(text)
        if not cleaned:
            return False
        if cls._contains_cjk(cleaned) or cls._contains_non_latin_script(cleaned):
            return True
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", cleaned)
        if not words:
            return False
        lowered = [w.lower() for w in words]
        english_hits = sum(1 for w in lowered if w in cls._ENGLISH_FUNCTION_WORDS)
        spanish_hits = sum(1 for w in lowered if w in cls._SPANISH_FUNCTION_WORDS)
        if len(lowered) < 4:
            if cls._is_term_like_phrase(lowered):
                return False
            if english_hits >= 1 and english_hits > spanish_hits:
                return True
            if spanish_hits == 0 and cls._looks_unstable_token_sequence(lowered):
                return True
            return False
        if spanish_hits == 0 and cls._looks_unstable_token_sequence(lowered):
            return True
        return english_hits >= (spanish_hits * 2 + 2)

    @classmethod
    def _looks_too_similar_to_source(cls, source_text: str, translated_text: str) -> bool:
        source = cls._sanitize(source_text).lower()
        translated = cls._sanitize(translated_text).lower()
        if not source or not translated:
            return False
        source_words = re.findall(r"[a-z0-9áéíóúüñ]+", source)
        translated_words = re.findall(r"[a-z0-9áéíóúüñ]+", translated)
        if len(source_words) < 3 or len(translated_words) < 3:
            return False
        if cls._is_term_like_phrase(translated_words):
            return False
        spanish_hits = sum(1 for w in translated_words if w in cls._SPANISH_FUNCTION_WORDS)
        if spanish_hits > 0:
            return False
        ratio = difflib.SequenceMatcher(None, " ".join(source_words), " ".join(translated_words), autojunk=False).ratio()
        return ratio >= 0.72

    @classmethod
    def _is_term_like_phrase(cls, words: list[str]) -> bool:
        if not words:
            return False
        for token in words:
            if token in cls._TERM_LIKE_TOKENS:
                continue
            if re.search(r"\d", token):
                continue
            if re.fullmatch(r"[a-z]{1,2}", token):
                continue
            return False
        return True

    async def _chat(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        *,
        model_override: Optional[str] = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        last_exc: Optional[Exception] = None
        if model_override:
            try:
                response = await self._client.chat.completions.create(
                    model=model_override,
                    temperature=0.0,
                    messages=messages,
                    max_tokens=self._max_completion_tokens,
                )
                content = response.choices[0].message.content or ""
                return self._sanitize(content)
            except APIStatusError as exc:
                last_exc = exc
                if exc.status_code not in (400, 404):
                    raise
            except Exception as exc:  # noqa: BLE001 - API boundary
                last_exc = exc
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

    @staticmethod
    def _load_energy_glossary(path: str) -> list[dict[str, str]]:
        if not path:
            return []
        glossary_path = Path(path)
        if not glossary_path.exists():
            return []
        rows: list[dict[str, str]] = []
        try:
            with glossary_path.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    term_en = (row.get("term_en") or "").strip()
                    term_es = (row.get("term_es") or "").strip()
                    rule = (row.get("rule") or "").strip().lower()
                    if not term_en or not term_es:
                        continue
                    rows.append(
                        {
                            "term_en": term_en,
                            "term_es": term_es,
                            "rule": rule or "translate",
                        }
                    )
        except OSError:
            return []
        return rows

    def _matched_domain_glossary(self, source_text: str, target_language: str) -> list[dict[str, str]]:
        if target_language.lower() != "spanish":
            return []
        if not self._energy_glossary:
            return []
        lowered = source_text.lower()
        matched: list[dict[str, str]] = []
        for item in self._energy_glossary:
            term_en = item["term_en"]
            if term_en.lower() not in lowered:
                continue
            matched.append(item)
            if len(matched) >= self._energy_glossary_max_rules:
                break
        return matched

    @staticmethod
    def _domain_glossary_prompt(domain_glossary: list[dict[str, str]]) -> str:
        if not domain_glossary:
            return ""
        return "; ".join(f"{item['term_en']} -> {item['term_es']} ({item['rule']})" for item in domain_glossary)

    @staticmethod
    def _apply_domain_glossary(
        *,
        source_text: str,
        translated_text: str,
        target_language: str,
        domain_glossary: list[dict[str, str]],
    ) -> str:
        if target_language.lower() != "spanish":
            return translated_text
        if not domain_glossary:
            return translated_text
        result = translated_text
        source_lower = source_text.lower()
        for item in domain_glossary:
            term_en = item["term_en"]
            term_es = item["term_es"]
            rule = item.get("rule", "translate")
            if term_en.lower() not in source_lower:
                continue
            if rule in {"keep_acronym", "keep_term"}:
                continue
            pattern = re.compile(rf"\b{re.escape(term_en)}\b", flags=re.IGNORECASE)
            result = pattern.sub(term_es, result)
        return re.sub(r"\s+", " ", result).strip()

    def _remember_turn(self, source_text: str, translated_text: str) -> None:
        normalized_source = self._sanitize(source_text)
        source_word_count = len(re.findall(r"\b\w+\b", normalized_source))
        if source_word_count < 4 or self._looks_incomplete_fragment(normalized_source):
            return
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

    @staticmethod
    def _should_use_context(text: str) -> bool:
        if TechnicalTranslationService._looks_incomplete_fragment(text):
            return False
        word_count = len(re.findall(r"\b\w+\b", text))
        if word_count < 10 or len(text.strip()) < 56:
            return False
        return re.search(r"[.!?]\s*$", text.strip()) is not None or word_count >= 14

    @staticmethod
    def _should_force_literal_translation(text: str) -> bool:
        word_count = len(re.findall(r"\b\w+\b", text))
        if word_count <= 6:
            return True
        return TechnicalTranslationService._looks_incomplete_fragment(text)

    @staticmethod
    def _looks_incomplete_fragment(text: str) -> bool:
        cleaned = TechnicalTranslationService._sanitize(text)
        if not cleaned:
            return False
        if re.search(r"[,:;/\\-]\s*$", cleaned):
            return True
        last_word_match = re.search(r"(\w+)\W*$", cleaned.lower())
        if not last_word_match:
            return False
        return last_word_match.group(1) in TechnicalTranslationService._INCOMPLETE_TRAILING_TOKENS

    def reset_context(self) -> None:
        self._recent_source.clear()
        self._recent_translations.clear()
        self._session_terms.clear()
        self._segments_routed = 0
        self._premium_segments = 0
        self.last_error = None
