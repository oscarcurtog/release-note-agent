#!/usr/bin/env python3
"""Shared wrappers for retries, watchdog timeouts, and degraded fallback."""

from __future__ import annotations

import time
from typing import Callable, Any, Iterable


def with_retries(
    fn: Callable[[], Any], *, max_attempts: int, backoff_s: float, retry_on: Iterable[str], classify_exc: Callable[[Exception], str]
) -> Any:
    attempt = 0
    while attempt < max_attempts:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            code = classify_exc(e)
            if code in retry_on and attempt + 1 < max_attempts:
                time.sleep(backoff_s * (2 ** attempt))
                attempt += 1
                continue
            raise


def with_watchdog(fn: Callable[[], Any], *, max_runtime_s: int, on_timeout: Callable[[], Any]) -> Any:
    t0 = time.perf_counter()
    try:
        result = fn()
    finally:
        elapsed = time.perf_counter() - t0
        if elapsed > max_runtime_s:
            try:
                on_timeout()
            finally:
                raise TimeoutError(f"Watchdog exceeded: {elapsed:.2f}s > {max_runtime_s}s")
    return result


def degraded_or_raise(primary: Callable[[], Any], fallback: Callable[[], Any], *, enable: bool) -> Any:
    if not enable:
        return primary()
    try:
        return primary()
    except Exception:
        return fallback()


