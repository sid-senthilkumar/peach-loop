"""Checkpoint save/load/verify for training runs.

Checkpoint layout per run (named by phase and epoch)::

    checkpoints/
    ├── phase1/
    │   ├── epoch_020/
    │   │   ├── adata.h5ad       # full AnnData — cell coords, uns, obs
    │   │   ├── model.pt         # torch state_dict of Deep_AA
    │   │   └── meta.json        # epoch, loss, timestamp, config hash
    │   └── epoch_040/
    │       └── ...
    └── phase2/
        └── variant_log_norm_hvg2000/
            └── seed_42/
                └── epoch_020/
                    └── ...

Design notes (see docs/decisions.md for rationale):
- We train in epoch chunks (size = config.checkpoints.interval_epochs).
- After each chunk we write the above layout.
- On resume, load the latest valid checkpoint (adata + model weights).
- PEACH stores model state in adata.uns; we also save the raw state_dict
  separately so we can reload without running PEACH init code.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from peach_loop.ops.logger import get_logger

log = get_logger("checkpoint")


def checkpoint_dir_for_epoch(base: Path, epoch: int) -> Path:
    return base / f"epoch_{epoch:04d}"


def save_checkpoint(
    adata: Any,
    results: dict,
    epoch: int,
    base_dir: Path,
    config_hash: str = "",
    max_to_keep: int = 5,
) -> Path:
    """Write one checkpoint.  Returns the checkpoint directory path."""
    import torch

    ckpt_dir = checkpoint_dir_for_epoch(base_dir, epoch)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save AnnData (contains PEACH's internal state in adata.uns['peach'])
    adata_path = ckpt_dir / "adata.h5ad"
    adata.write_h5ad(adata_path)

    # 2. Save model state_dict separately for robust reloading
    model = results.get("model")
    if model is not None and hasattr(model, "state_dict"):
        torch.save(model.state_dict(), ckpt_dir / "model.pt")

    # 3. Metadata
    history = results.get("history", {})
    last_loss = None
    if history:
        losses = history.get("loss", [])
        if losses:
            last_loss = float(losses[-1])

    meta = {
        "epoch": epoch,
        "ts": datetime.now(timezone.utc).isoformat(),
        "loss": last_loss,
        "final_archetype_r2": results.get("final_archetype_r2"),
        "best_epoch": results.get("best_epoch"),
        "config_hash": config_hash,
    }
    with open(ckpt_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    log.info(f"Checkpoint saved: {ckpt_dir}  (epoch {epoch}, loss {last_loss})")

    _cleanup_old_checkpoints(base_dir, keep=max_to_keep)
    return ckpt_dir


def load_checkpoint(ckpt_dir: Path) -> tuple[Any, dict]:
    """Load adata and metadata from a checkpoint directory.

    Returns (adata, meta_dict).  Does not reload the model into adata.uns;
    caller should call PEACH's train_archetypal with the loaded adata so PEACH
    can warm-start from adata.uns state.
    """
    import anndata

    adata_path = ckpt_dir / "adata.h5ad"
    meta_path = ckpt_dir / "meta.json"

    if not adata_path.exists():
        raise FileNotFoundError(f"Checkpoint missing adata.h5ad: {ckpt_dir}")

    adata = anndata.read_h5ad(adata_path)
    meta = {}
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)

    log.info(f"Checkpoint loaded: {ckpt_dir}  (epoch {meta.get('epoch', '?')})")
    return adata, meta


def load_model_state(ckpt_dir: Path) -> Optional[dict]:
    """Return the raw torch state_dict from a checkpoint, or None if not saved."""
    import torch

    model_path = ckpt_dir / "model.pt"
    if not model_path.exists():
        return None
    return torch.load(model_path, map_location="cpu")


def verify_checkpoint(ckpt_dir: Path) -> bool:
    """Return True iff the checkpoint can be loaded without error."""
    try:
        adata, meta = load_checkpoint(ckpt_dir)
        assert adata is not None
        assert "epoch" in meta
        return True
    except Exception as exc:
        log.warning(f"Checkpoint verification failed for {ckpt_dir}: {exc}")
        return False


def get_latest_checkpoint(base_dir: Path) -> Optional[Path]:
    """Return the most recent valid checkpoint directory, or None."""
    if not base_dir.exists():
        return None
    candidates = sorted(base_dir.glob("epoch_*"), reverse=True)
    for candidate in candidates:
        if verify_checkpoint(candidate):
            return candidate
    return None


def _cleanup_old_checkpoints(base_dir: Path, keep: int) -> None:
    """Delete oldest checkpoint directories, keeping the `keep` most recent."""
    candidates = sorted(base_dir.glob("epoch_*"))
    to_delete = candidates[: max(0, len(candidates) - keep)]
    for old in to_delete:
        shutil.rmtree(old, ignore_errors=True)
        log.debug(f"Deleted old checkpoint: {old}")
