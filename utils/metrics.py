#!/usr/bin/env python3
"""Minimal metrics (counters and timers) written as JSONL.

Windows/CI-friendly; avoids sockets. Redact by design: caller should avoid
passing large or sensitive strings.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

from configs.config import Config


def _path() -> Path:
    root = Path(getattr(Config, "METRICS_ROOT", ".cache/release_notes/metrics"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "metrics.log"


def incr(name: str, value: Any = 1, **kw) -> None:
    if not getattr(Config, "METRICS_ENABLED", True):
        return
    rec: Dict[str, Any] = {"ts": int(time.time()), "metric": name, "value": value}
    for k, v in kw.items():
        if isinstance(v, str) and len(v) > 200:
            rec[k] = v[:200] + "…"
        else:
            rec[k] = v
    p = _path()
    line = json.dumps(rec, separators=(",", ":")) + "\n"
    with open(p, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


class Timer:
    def __init__(self, name: str, **kw):
        self.name = name
        self.kw = kw
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        dt = time.perf_counter() - self._t0
        incr(name=f"{self.name}.latency_s", value=dt, **self.kw)


