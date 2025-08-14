#!/usr/bin/env python3
"""Simple file-backed circuit breaker with CLOSED/OPEN/HALF_OPEN states.

Windows-friendly (no signals). Uses atomic JSON state files under a configurable
root. Suitable for per-dependency guarding (e.g., bedrock, github_api).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal


State = Literal["CLOSED", "OPEN", "HALF_OPEN"]


@dataclass
class CBConfig:
    failure_threshold: int = 5
    recovery_time_s: int = 120
    half_open_max_calls: int = 1
    state_root: str = ".cache/release_notes/cb"


class CircuitBreaker:
    """File-backed circuit breaker.

    State model:
      - CLOSED: calls allowed; consecutive failures increment counter
      - OPEN: calls denied until recovery time has elapsed
      - HALF_OPEN: allow up to N probe calls; success -> CLOSED; failure -> OPEN
    """

    def __init__(self, name: str, cfg: CBConfig):
        self.name = name
        self.cfg = cfg
        Path(self.cfg.state_root).mkdir(parents=True, exist_ok=True)

    def _path(self) -> Path:
        safe = self.name.replace("/", "#").replace(os.sep, "#")
        return Path(self.cfg.state_root) / f"{safe}.cb.json"

    def _load(self) -> Dict:
        p = self._path()
        if not p.exists():
            return {"state": "CLOSED", "failures": 0, "ts_open": 0, "half_open_calls": 0}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"state": "CLOSED", "failures": 0, "ts_open": 0, "half_open_calls": 0}

    def _save(self, data: Dict) -> None:
        p = self._path()
        tmp = p.with_suffix(p.suffix + ".tmp")
        body = json.dumps(data, separators=(",", ":"))
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)

    def state(self) -> State:
        data = self._load()
        return data.get("state", "CLOSED")  # type: ignore[return-value]

    def allow(self) -> bool:
        now = int(time.time())
        data = self._load()
        st = data.get("state", "CLOSED")
        if st == "OPEN":
            ts = int(data.get("ts_open", 0))
            if now - ts >= self.cfg.recovery_time_s:
                # Move to HALF_OPEN
                data["state"] = "HALF_OPEN"
                data["half_open_calls"] = 0
                self._save(data)
                return True
            return False
        if st == "HALF_OPEN":
            hoc = int(data.get("half_open_calls", 0))
            if hoc < self.cfg.half_open_max_calls:
                data["half_open_calls"] = hoc + 1
                self._save(data)
                return True
            return False
        # CLOSED
        return True

    def record_success(self) -> None:
        data = self._load()
        data.update({"state": "CLOSED", "failures": 0, "ts_open": 0, "half_open_calls": 0})
        self._save(data)

    def record_failure(self) -> None:
        data = self._load()
        failures = int(data.get("failures", 0)) + 1
        data["failures"] = failures
        if failures >= self.cfg.failure_threshold:
            data["state"] = "OPEN"
            data["ts_open"] = int(time.time())
            data["half_open_calls"] = 0
        self._save(data)


