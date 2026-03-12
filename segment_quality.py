from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from config_utils import read_bool_env, read_float_env, read_int_env

TranslationRoute = Literal["normal", "premium", "drop"]
SegmentStage = Literal["preview", "commit", "drop"]


@dataclass(slots=True)
class SegmentDecision:
    stage: SegmentStage
    route: TranslationRoute
    text: str
    semantic_score: float
    language_guard_triggered: bool
    source_confidence: float = 0.0
    source_incomplete: bool = False
    mixed_script_detected: bool = False
    non_target_language_detected: bool = False
    translation_too_similar_to_source: bool = False
    semantic_drift_score: float = 1.0
    emit_interval_s: float = 0.0
    dropped_reason: str = ""


@dataclass(slots=True)
class SegmentSignals:
    source_confidence: float
    source_incomplete: bool
    mixed_script_detected: bool
    non_target_language_detected: bool
    translation_too_similar_to_source: bool
    semantic_score: float
    semantic_drift_score: float


class SegmentQualityGate:
    _ENGLISH_FUNCTION_WORDS = {
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
    _SPANISH_FUNCTION_WORDS = {
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
    _DEFAULT_REJECT_PATTERNS = (
        "lo siento, no puedo ayudar con eso",
        "lo siento, no puedo ayudarte con eso",
        "i'm sorry, i can't help with that",
        "i cannot help with that",
        "cannot assist with that",
    )

    def __init__(self) -> None:
        self.dual_pass_enabled = read_bool_env("DUAL_PASS_ENABLED", True)
        self.preview_min_words = read_int_env("PREVIEW_MIN_WORDS", 3)
        self.preview_max_age_seconds = read_float_env("PREVIEW_MAX_AGE_SECONDS", 0.45)
        self.commit_min_words = read_int_env("COMMIT_MIN_WORDS", 5)
        self.commit_max_age_seconds = read_float_env("COMMIT_MAX_AGE_SECONDS", 1.4)
        self.semantic_guard_enabled = read_bool_env("SEMANTIC_GUARD_ENABLED", True)
        self.semantic_guard_min_score = read_float_env("SEMANTIC_GUARD_MIN_SCORE", 0.78)
        self.source_guard_enabled = read_bool_env("SOURCE_GUARD_ENABLED", True)
        self.source_preview_min_confidence = read_float_env("SOURCE_PREVIEW_MIN_CONFIDENCE", 0.28)
        self.source_commit_min_confidence = read_float_env("SOURCE_COMMIT_MIN_CONFIDENCE", 0.39)
        self.drop_similar_to_source = read_bool_env("DROP_SIMILAR_TO_SOURCE_ENABLED", True)
        reject_path = (os.getenv("REJECT_PHRASES_PATH") or "./bench/reject_phrases_es.txt").strip()
        self.reject_patterns = self._load_reject_patterns(reject_path)

    def inspect_segment(self, *, source_text: str, translated_text: str, target_language: str) -> SegmentSignals:
        cleaned_source = self._sanitize(source_text)
        cleaned_translation = self._sanitize(translated_text)
        source_confidence = self.confidence_from_source(cleaned_source)
        source_incomplete = self._source_incomplete(cleaned_source)
        mixed_script_detected = self._contains_disallowed_script(cleaned_translation)
        non_target_language_detected = self._language_guard(cleaned_translation, target_language)
        translation_too_similar = self._looks_too_similar_to_source(cleaned_source, cleaned_translation)
        semantic_score = self.semantic_score(
            source_text=cleaned_source,
            translated_text=cleaned_translation,
            target_language=target_language,
        )
        return SegmentSignals(
            source_confidence=source_confidence,
            source_incomplete=source_incomplete,
            mixed_script_detected=mixed_script_detected,
            non_target_language_detected=non_target_language_detected,
            translation_too_similar_to_source=translation_too_similar,
            semantic_score=semantic_score,
            semantic_drift_score=max(0.0, 1.0 - semantic_score),
        )

    def decide_preview(
        self,
        *,
        source_text: str,
        translated_text: str,
        target_language: str,
        route: TranslationRoute,
        pending_age_s: float,
    ) -> SegmentDecision:
        cleaned = self._sanitize(translated_text)
        if not cleaned:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=0.0,
                language_guard_triggered=False,
                dropped_reason="preview_empty",
            )
        if self._matches_reject_pattern(cleaned):
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=0.0,
                language_guard_triggered=False,
                dropped_reason="reject_phrase",
            )
        words = self._word_count(cleaned)
        signals = self.inspect_segment(
            source_text=source_text,
            translated_text=cleaned,
            target_language=target_language,
        )
        if signals.non_target_language_detected:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=True,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="language_guard",
            )
        if self.source_guard_enabled and signals.source_confidence < self.source_preview_min_confidence:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=False,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="source_low_confidence",
            )
        if self.drop_similar_to_source and signals.translation_too_similar_to_source:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=False,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="translation_too_similar",
            )
        if words < self.preview_min_words and pending_age_s < self.preview_max_age_seconds:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=False,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="preview_too_short",
            )
        if self.semantic_guard_enabled and signals.semantic_score < (self.semantic_guard_min_score * 0.72):
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=False,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="preview_semantic_low",
            )
        return SegmentDecision(
            stage="preview",
            route=route,
            text=cleaned,
            semantic_score=signals.semantic_score,
            language_guard_triggered=False,
            source_confidence=signals.source_confidence,
            source_incomplete=signals.source_incomplete,
            mixed_script_detected=signals.mixed_script_detected,
            non_target_language_detected=signals.non_target_language_detected,
            translation_too_similar_to_source=signals.translation_too_similar_to_source,
            semantic_drift_score=signals.semantic_drift_score,
        )

    def decide_commit(
        self,
        *,
        source_text: str,
        translated_text: str,
        target_language: str,
        route: TranslationRoute,
        pending_age_s: float,
    ) -> SegmentDecision:
        cleaned = self._sanitize(translated_text)
        if not cleaned:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=0.0,
                language_guard_triggered=False,
                dropped_reason="commit_empty",
            )
        if self._matches_reject_pattern(cleaned):
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=0.0,
                language_guard_triggered=False,
                dropped_reason="reject_phrase",
            )
        words = self._word_count(cleaned)
        signals = self.inspect_segment(
            source_text=source_text,
            translated_text=cleaned,
            target_language=target_language,
        )
        if signals.non_target_language_detected:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=True,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="language_guard",
            )
        if self.source_guard_enabled and signals.source_confidence < self.source_commit_min_confidence:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=False,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="source_low_confidence",
            )
        if self.drop_similar_to_source and signals.translation_too_similar_to_source:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=False,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="translation_too_similar",
            )
        if words == 1:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=False,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="single_word_final",
            )
        if words < self.commit_min_words and pending_age_s < self.commit_max_age_seconds:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=False,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="commit_too_short",
            )
        if self.semantic_guard_enabled and signals.semantic_score < self.semantic_guard_min_score:
            return SegmentDecision(
                stage="drop",
                route="drop",
                text="",
                semantic_score=signals.semantic_score,
                language_guard_triggered=False,
                source_confidence=signals.source_confidence,
                source_incomplete=signals.source_incomplete,
                mixed_script_detected=signals.mixed_script_detected,
                non_target_language_detected=signals.non_target_language_detected,
                translation_too_similar_to_source=signals.translation_too_similar_to_source,
                semantic_drift_score=signals.semantic_drift_score,
                dropped_reason="semantic_low",
            )
        return SegmentDecision(
            stage="commit",
            route=route,
            text=cleaned,
            semantic_score=signals.semantic_score,
            language_guard_triggered=False,
            source_confidence=signals.source_confidence,
            source_incomplete=signals.source_incomplete,
            mixed_script_detected=signals.mixed_script_detected,
            non_target_language_detected=signals.non_target_language_detected,
            translation_too_similar_to_source=signals.translation_too_similar_to_source,
            semantic_drift_score=signals.semantic_drift_score,
        )

    def confidence_from_source(self, source_text: str) -> float:
        cleaned = self._sanitize(source_text)
        if not cleaned:
            return 0.0
        words = self._word_count(cleaned)
        if words <= 2:
            return 0.45
        punctuation_bonus = 0.1 if re.search(r"[.!?]\s*$", cleaned) else 0.0
        connector_penalty = 0.18 if re.search(r"(and|or|but|with|for|to|de|con|y)\s*$", cleaned.lower()) else 0.0
        density = min(1.0, words / 10.0)
        length_term = min(1.0, len(cleaned) / 64.0)
        score = (0.55 * density) + (0.35 * length_term) + punctuation_bonus - connector_penalty
        return max(0.0, min(1.0, score))

    def _source_incomplete(self, source_text: str) -> bool:
        cleaned = self._sanitize(source_text)
        if not cleaned:
            return True
        if re.search(r"[,:;/\\-]\s*$", cleaned):
            return True
        last_word_match = re.search(r"(\w+)\W*$", cleaned.lower())
        if last_word_match and last_word_match.group(1) in self._ENGLISH_FUNCTION_WORDS.union(self._SPANISH_FUNCTION_WORDS):
            return True
        return not re.search(r"[.!?]\s*$", cleaned) and self._word_count(cleaned) < max(4, self.commit_min_words)

    def semantic_score(self, *, source_text: str, translated_text: str, target_language: str) -> float:
        source = self._sanitize(source_text)
        translated = self._sanitize(translated_text)
        if not source or not translated:
            return 0.0

        src_words = self._word_count(source)
        tgt_words = self._word_count(translated)
        if tgt_words == 0:
            return 0.0

        ratio = tgt_words / max(1, src_words)
        ratio_score = 1.0 - min(1.0, abs(1.0 - ratio) / 1.2)
        char_ratio = len(translated) / max(1, len(source))
        char_score = 1.0 - min(1.0, abs(1.0 - char_ratio) / 1.4)
        fluency_score = 0.85
        if re.search(r"[.!?]\s*$", translated):
            fluency_score = 1.0
        elif tgt_words <= 2:
            fluency_score = 0.58
        unstable_penalty = 0.25 if self._looks_unstable(translated) else 0.0
        language_penalty = 0.35 if self._language_guard(translated, target_language) else 0.0

        score = (0.4 * ratio_score) + (0.3 * char_score) + (0.3 * fluency_score) - unstable_penalty - language_penalty
        return max(0.0, min(1.0, score))

    @staticmethod
    def _sanitize(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    @staticmethod
    def _word_count(text: str) -> int:
        return len(re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ]+\b", text or ""))

    @staticmethod
    def _contains_disallowed_script(text: str) -> bool:
        return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u0400-\u052F\u0590-\u05FF\u0600-\u06FF\u0750-\u077F]", text or ""))

    def _language_guard(self, text: str, target_language: str) -> bool:
        cleaned = self._sanitize(text)
        if not cleaned:
            return False
        if self._contains_disallowed_script(cleaned):
            return True
        if (target_language or "").strip().lower() != "spanish":
            return False
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", cleaned)
        if not words:
            return False
        lowered = [w.lower() for w in words]
        english_hits = sum(1 for w in lowered if w in self._ENGLISH_FUNCTION_WORDS)
        spanish_hits = sum(1 for w in lowered if w in self._SPANISH_FUNCTION_WORDS)
        if len(lowered) < 4:
            return english_hits >= 2 and spanish_hits == 0
        return english_hits >= (spanish_hits * 2 + 2)

    def _looks_too_similar_to_source(self, source_text: str, translated_text: str) -> bool:
        source = self._sanitize(source_text).lower()
        translated = self._sanitize(translated_text).lower()
        if not source or not translated:
            return False
        source_words = re.findall(r"[a-z0-9áéíóúüñ]+", source)
        translated_words = re.findall(r"[a-z0-9áéíóúüñ]+", translated)
        if len(source_words) < 3 or len(translated_words) < 3:
            return False
        spanish_hits = sum(1 for token in translated_words if token in self._SPANISH_FUNCTION_WORDS)
        if spanish_hits > 0:
            return False
        ratio = difflib.SequenceMatcher(
            None,
            " ".join(source_words),
            " ".join(translated_words),
            autojunk=False,
        ).ratio()
        return ratio >= 0.72

    @staticmethod
    def _looks_unstable(text: str) -> bool:
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", text or "")
        if not words:
            return False
        unstable = 0
        for token in words:
            lowered = token.lower()
            if len(lowered) <= 2:
                continue
            if re.search(r"[bcdfghjklmnñpqrstvwxyz]{5,}", lowered):
                unstable += 1
                continue
            if len(lowered) >= 7 and not re.search(r"[aeiouáéíóúü]", lowered):
                unstable += 1
        return unstable >= max(1, len(words) // 3)

    @classmethod
    def _load_reject_patterns(cls, path: str) -> list[str]:
        patterns = [pattern.strip().lower() for pattern in cls._DEFAULT_REJECT_PATTERNS]
        file_path = Path(path)
        if not file_path.exists():
            return patterns
        try:
            for line in file_path.read_text(encoding="utf-8").splitlines():
                cleaned = line.strip()
                if not cleaned or cleaned.startswith("#"):
                    continue
                if cleaned.lower().startswith("ejemplo:"):
                    phrase = cleaned.split(":", 1)[1].strip().strip('"').strip("'").lower()
                    if phrase:
                        patterns.append(phrase)
        except OSError:
            return patterns
        deduped: list[str] = []
        seen = set()
        for item in patterns:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _matches_reject_pattern(self, text: str) -> bool:
        lowered = self._sanitize(text).lower()
        if not lowered:
            return False
        return any(pattern in lowered for pattern in self.reject_patterns)
