"""KB root path resolution. Imported by every handler that writes."""
from __future__ import annotations
import os
from pathlib import Path


def resolve_kb_root(cli_arg: str | Path | None = None) -> Path:
    """Resolve the user's KB root.

    Priority:
      1. Explicit CLI arg if provided
      2. ``$QLW_KB_ROOT`` env var
      3. Current working directory

    Always returns an absolute, expanduser'd Path. Resolved at call time;
    never cache the result at module level.
    """
    if cli_arg:
        return Path(cli_arg).expanduser().resolve()
    env = os.environ.get("QLW_KB_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()
