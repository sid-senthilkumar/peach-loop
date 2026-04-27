"""Logging setup.

Two outputs:
  - Console: human-readable, level-filtered.
  - events.jsonl: one JSON object per event, machine-readable, append-only.
  - training.jsonl: one JSON object per training step metric flush.

Per AGENTS.md §10: per-step metrics at minimum every 10 steps; all logs protected.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_event_logger: logging.Logger | None = None
_training_file: Path | None = None


def setup_logging(log_dir: str | Path, level: str = "INFO") -> logging.Logger:
    """Initialise the root logger and open the event log file.

    Call once at process startup.  Subsequent calls return the cached logger.
    """
    global _event_logger, _training_file

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    if _event_logger is not None:
        return _event_logger

    _training_file = log_dir.parent / "training" / "training.jsonl"
    _training_file.parent.mkdir(parents=True, exist_ok=True)

    # Root logger — console handler only (JSON handler added separately below)
    root = logging.getLogger("peach_loop")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not root.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"))
        root.addHandler(ch)

        # JSON event log
        event_path = log_dir / "events.jsonl"
        fh = _JsonFileHandler(event_path)
        fh.setLevel(logging.DEBUG)
        root.addHandler(fh)

    _event_logger = root
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the peach_loop hierarchy."""
    return logging.getLogger(f"peach_loop.{name}")


def log_training_step(
    step: int,
    epoch: int,
    loss_total: float,
    loss_components: dict[str, float],
    extra: dict[str, Any] | None = None,
) -> None:
    """Write one training-step record to training.jsonl.

    Called every ``logging.per_step_interval`` steps.
    loss_components should contain: reconstruction, archetypal, diversity,
    regularity, sparsity, manifold — whatever PEACH reports.
    """
    if _training_file is None:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "step": step,
        "epoch": epoch,
        "loss": loss_total,
        **{f"loss_{k}": v for k, v in loss_components.items()},
        **(extra or {}),
    }
    with open(_training_file, "a") as f:
        f.write(json.dumps(record) + "\n")


def log_event(
    category: str,
    message: str,
    level: str = "INFO",
    extra: dict[str, Any] | None = None,
) -> None:
    """Write a structured event directly (bypasses Python logging handlers)."""
    logger = get_logger(category)
    log_fn = getattr(logger, level.lower(), logger.info)
    log_fn(message, extra=extra or {})


class _JsonFileHandler(logging.FileHandler):
    """Logging handler that writes newline-delimited JSON to a file."""

    def emit(self, record: logging.LogRecord) -> None:
        obj = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        try:
            with open(self.baseFilename, "a") as f:
                f.write(json.dumps(obj) + "\n")
        except Exception:
            self.handleError(record)


def read_last_n_log_lines(log_path: Path, n: int = 100) -> list[str]:
    """Return the last n lines from a .jsonl log file (for Tier-1 staging)."""
    if not log_path.exists():
        return []
    with open(log_path) as f:
        lines = f.readlines()
    return lines[-n:]
