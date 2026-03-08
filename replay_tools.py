from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FixtureSpec:
    fixture_id: str
    title: str = "N/D"
    source_url: str = "N/D"
    source_type: str = "youtube"
    clip_start_s: float = 0.0
    duration_s: float = 0.0
    audio_path: str = ""
    reference_caption_path: str = ""
    reference_transcript_path: str = ""
    notes: str = ""
    target_language: str = "Spanish"


@dataclass(slots=True)
class SubtitleCue:
    start_s: float
    end_s: float
    text: str


def load_replay_manifest(path: Path) -> dict[str, FixtureSpec]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    parsed = _load_yaml_like(raw)
    fixtures = parsed.get("fixtures", [])
    result: dict[str, FixtureSpec] = {}
    for item in fixtures:
        fixture = _fixture_from_dict(item, base_dir=path.parent)
        if fixture is None:
            continue
        result[fixture.fixture_id] = fixture
    return result


def load_subtitle_cues(path: Path) -> list[SubtitleCue]:
    if not path.exists():
        return []
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".vtt":
        return _parse_webvtt(raw)
    if suffix == ".srt":
        return _parse_srt(raw)
    if suffix == ".json":
        return _parse_json_cues(raw)
    return []


def match_reference_cue(cues: list[SubtitleCue], audio_t0: float, audio_t1: float) -> SubtitleCue | None:
    if not cues:
        return None
    end_s = max(audio_t0, audio_t1)
    best_cue: SubtitleCue | None = None
    best_overlap = -1.0
    for cue in cues:
        overlap = min(end_s, cue.end_s) - max(audio_t0, cue.start_s)
        if overlap > best_overlap:
            best_overlap = overlap
            best_cue = cue
    if best_cue is not None and best_overlap > 0:
        return best_cue

    target_mid = (audio_t0 + end_s) / 2.0
    return min(cues, key=lambda cue: abs(((cue.start_s + cue.end_s) / 2.0) - target_mid))


def _fixture_from_dict(item: dict[str, Any], *, base_dir: Path) -> FixtureSpec | None:
    fixture_id = str(item.get("fixture_id", "")).strip()
    if not fixture_id:
        return None
    return FixtureSpec(
        fixture_id=fixture_id,
        title=str(item.get("title", "N/D") or "N/D"),
        source_url=str(item.get("source_url", "N/D") or "N/D"),
        source_type=str(item.get("source_type", "youtube") or "youtube"),
        clip_start_s=_as_float(item.get("clip_start_s", 0.0)),
        duration_s=_as_float(item.get("duration_s", 0.0)),
        audio_path=_resolve_path(base_dir, str(item.get("audio_path", "") or "")),
        reference_caption_path=_resolve_path(base_dir, str(item.get("reference_caption_path", "") or "")),
        reference_transcript_path=_resolve_path(base_dir, str(item.get("reference_transcript_path", "") or "")),
        notes=str(item.get("notes", "") or ""),
        target_language=str(item.get("target_language", "Spanish") or "Spanish"),
    )


def _resolve_path(base_dir: Path, raw_path: str) -> str:
    cleaned = raw_path.strip()
    if not cleaned:
        return ""
    candidate = Path(cleaned)
    if candidate.is_absolute():
        return str(candidate)
    return str((base_dir / candidate).resolve())


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _load_yaml_like(raw: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(raw) or {}
    except Exception:
        pass

    result: dict[str, Any] = {"fixtures": []}
    current: dict[str, Any] | None = None
    in_fixtures = False
    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "fixtures:":
            in_fixtures = True
            continue
        if not in_fixtures:
            continue
        if stripped.startswith("- "):
            if current:
                result["fixtures"].append(current)
            current = {}
            stripped = stripped[2:].strip()
            if stripped and ":" in stripped:
                key, value = stripped.split(":", 1)
                current[key.strip()] = _parse_scalar(value.strip())
            continue
        if current is None or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        current[key.strip()] = _parse_scalar(value.strip())
    if current:
        result["fixtures"].append(current)
    return result


def _parse_scalar(raw: str) -> Any:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    if cleaned[0] in {'"', "'"} and cleaned[-1] == cleaned[0]:
        return cleaned[1:-1]
    if cleaned.lower() in {"true", "false"}:
        return cleaned.lower() == "true"
    if re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
        return float(cleaned) if "." in cleaned else int(cleaned)
    return cleaned


def _parse_webvtt(raw: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    current_start = 0.0
    current_end = 0.0
    text_lines: list[str] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip("\ufeff")
        stripped = line.strip()
        if not stripped:
            if text_lines:
                cues.append(SubtitleCue(current_start, current_end, _collapse_text(text_lines)))
                text_lines = []
            continue
        if stripped.startswith("WEBVTT") or stripped.startswith("NOTE"):
            continue
        if "-->" in stripped:
            start_raw, end_raw = [part.strip().split(" ", 1)[0] for part in stripped.split("-->", 1)]
            current_start = _parse_timestamp(start_raw)
            current_end = _parse_timestamp(end_raw)
            continue
        if re.fullmatch(r"\d+", stripped):
            continue
        text_lines.append(stripped)
    if text_lines:
        cues.append(SubtitleCue(current_start, current_end, _collapse_text(text_lines)))
    return [cue for cue in cues if cue.text]


def _parse_srt(raw: str) -> list[SubtitleCue]:
    return _parse_webvtt(raw)


def _parse_json_cues(raw: str) -> list[SubtitleCue]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    cues: list[SubtitleCue] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cues.append(
            SubtitleCue(
                start_s=_as_float(item.get("start_s", 0.0)),
                end_s=_as_float(item.get("end_s", 0.0)),
                text=str(item.get("text", "") or "").strip(),
            )
        )
    return [cue for cue in cues if cue.text]


def _collapse_text(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_timestamp(raw: str) -> float:
    cleaned = raw.replace(",", ".").strip()
    parts = cleaned.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        return 0.0
    try:
        return (int(hours) * 3600.0) + (int(minutes) * 60.0) + float(seconds)
    except ValueError:
        return 0.0
