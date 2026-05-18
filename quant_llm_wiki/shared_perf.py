"""Shared performance instrumentation helper. Env-gated, zero-cost when off."""
from __future__ import annotations

import os
import sys


def _emit_perf(event: str, **fields) -> None:
    """Emit a single [qlw-perf] line when QLW_PERF_DEBUG is set. Zero-cost when off."""
    if not os.environ.get("QLW_PERF_DEBUG"):
        return
    parts = []
    for k, v in fields.items():
        if isinstance(v, float):
            parts.append(f"{k}={v:.3f}")
        else:
            parts.append(f"{k}={v}")
    print(f"[qlw-perf] {event}: {' '.join(parts)}", file=sys.stderr)
