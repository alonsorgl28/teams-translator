from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class ReplayEventLogger:
    def __init__(self, enabled: bool, output_path: str) -> None:
        self._enabled = enabled
        self._output_path = Path(output_path)
        self._session_started_at: Optional[datetime] = None
        self._fixture_id = "N/D"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start_session(self, fixture_id: str, *, started_at: Optional[datetime] = None) -> None:
        if not self._enabled:
            return
        self._fixture_id = fixture_id or "N/D"
        self._session_started_at = started_at or datetime.now()
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_path.write_text("", encoding="utf-8")

    def record_event(self, payload: dict[str, Any]) -> None:
        if not self._enabled:
            return
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        if "recorded_at" not in payload:
            payload["recorded_at"] = datetime.now().isoformat(timespec="milliseconds")
        payload.setdefault("fixture_id", self._fixture_id)
        with self._output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")
