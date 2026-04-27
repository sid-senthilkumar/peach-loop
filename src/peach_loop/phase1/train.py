"""PEACH training with checkpointing for Phase 1.

Training strategy:
  - Run pc.tl.train_archetypal in epoch chunks (chunk size = config.checkpoints.interval_epochs).
  - After each chunk, save a checkpoint (adata.h5ad + model.pt + meta.json).
  - On resume, load the latest checkpoint and continue from the saved epoch.
  - PEACH is expected to warm-start from adata.uns['peach'] if present;
    see docs/decisions.md for the assumption and fallback.

Device selection:
  - "auto" → try CUDA, then MPS, then CPU.
  - Fall back to CPU on MPS instability (Tier-2 protocol, AGENTS.md §9).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from peach_loop.ops.logger import get_logger, log_training_step
from peach_loop.ops.state import RunState, record_tier2_event

log = get_logger("phase1.train")

# AGENTS.md §8: PCHA init failure is a Tier-1 condition.
PCHA_DEGENERATE_THRESHOLD = 1e-6  # archetype coordinate variance below this = collapsed


def select_device(preference: str = "auto") -> str:
    """Return the best available device string."""
    import torch

    if preference not in ("auto", "cuda", "mps", "cpu"):
        log.warning(f"Unknown device preference '{preference}', using 'auto'")
        preference = "auto"

    if preference == "cpu":
        return "cpu"
    if preference == "cuda":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if preference == "mps":
        return "mps" if torch.backends.mps.is_available() else "cpu"

    # auto
    if torch.cuda.is_available():
        log.info("Device: CUDA")
        return "cuda"
    if torch.backends.mps.is_available():
        log.info("Device: MPS (Apple Silicon) — will fall back to CPU if unstable")
        return "mps"
    log.info("Device: CPU")
    return "cpu"


def run_hyperparameter_search(adata: Any, config: Any) -> int:
    """Run PEACH's hyperparameter search to pick n_archetypes.

    Falls back to config.peach.hyperparameter_search.fallback_n_archetypes
    if the search exceeds its wall-clock cap.
    """
    import peach as pc

    hs = getattr(getattr(config, "peach", config), "hyperparameter_search", None)
    if hs is None:
        return 5  # safe default

    n_range = list(getattr(hs, "n_archetypes_range", [3, 4, 5, 6, 7, 8]))
    cv_folds = int(getattr(hs, "cv_folds", 3))
    max_epochs_cv = int(getattr(hs, "max_epochs_cv", 15))
    cap_minutes = float(getattr(hs, "wall_clock_cap_minutes", 30))
    fallback = int(getattr(hs, "fallback_n_archetypes", 5))

    log.info(f"Hyperparameter search: n_archetypes in {n_range}, {cv_folds} folds")
    start = time.monotonic()
    try:
        cv_summary = pc.tl.hyperparameter_search(
            adata,
            n_archetypes_range=n_range,
            cv_folds=cv_folds,
            max_epochs_cv=max_epochs_cv,
        )
        elapsed = time.monotonic() - start
        if elapsed > cap_minutes * 60:
            log.warning(
                f"Hyperparameter search took {elapsed/60:.1f} min (cap={cap_minutes} min) — "
                f"using result anyway (cap is informational at this point)"
            )
        n_best = cv_summary.get("best_n_archetypes", fallback)
        log.info(f"Hyperparameter search complete: best n_archetypes = {n_best}")
        return int(n_best)
    except Exception as exc:
        elapsed = time.monotonic() - start
        log.warning(
            f"Hyperparameter search failed after {elapsed:.1f}s ({exc}) — "
            f"falling back to n_archetypes = {fallback}"
        )
        return fallback


def train_with_checkpoints(
    adata: Any,
    n_archetypes: int,
    config: Any,
    checkpoint_base: Path,
    state: RunState,
    state_path: Path,
    start_epoch: int = 0,
    device: Optional[str] = None,
) -> tuple[Any, dict]:
    """Train PEACH in epoch chunks, saving a checkpoint after each chunk.

    Returns (adata_with_results, final_results_dict).

    start_epoch > 0 means we are resuming; the adata should already contain
    PEACH's warm-start state in adata.uns.
    """
    import peach as pc
    from peach_loop.ops.checkpoint import save_checkpoint
    from peach_loop.ops.state import save_state
    from peach_loop.ops.tier1 import check_loss_divergence, raise_tier1, Tier1Condition
    from peach_loop.ops.tier2 import handle_mps_instability

    peach_cfg = getattr(config, "peach", config)
    total_epochs = int(getattr(peach_cfg, "n_epochs", 150))
    chunk_size = int(getattr(getattr(config, "checkpoints", config), "interval_epochs", 20))
    max_to_keep = int(getattr(getattr(config, "checkpoints", config), "max_to_keep", 5))

    if device is None:
        device = select_device(getattr(peach_cfg, "device", "auto"))

    log.info(
        f"Training: n_archetypes={n_archetypes}, total_epochs={total_epochs}, "
        f"chunk_size={chunk_size}, device={device}, start_epoch={start_epoch}"
    )

    results: dict = {}
    all_losses: list[float] = []
    step_counter = 0
    log_interval = int(getattr(getattr(config, "logging", config), "per_step_interval", 10))

    wall_cap_hours = float(getattr(config, "wall_clock_cap_hours", 4))
    phase_start = time.monotonic()

    for chunk_start in range(start_epoch, total_epochs, chunk_size):
        # Wall-clock cap check (Tier-1)
        if (time.monotonic() - phase_start) > wall_cap_hours * 3600:
            raise_tier1(
                Tier1Condition.WALL_CLOCK_CAP_HIT,
                f"Phase 1 wall-clock cap ({wall_cap_hours}h) hit during training at epoch {chunk_start}",
                state, state_path,
                checkpoint_base.parent.parent / "logs",
            )

        chunk_end = min(chunk_start + chunk_size, total_epochs)
        epochs_this_chunk = chunk_end - chunk_start
        log.info(f"Training epochs {chunk_start + 1}–{chunk_end} …")

        mps_retry = False
        while True:
            try:
                results = pc.tl.train_archetypal(
                    adata,
                    n_archetypes=n_archetypes,
                    n_epochs=epochs_this_chunk,
                    device=device,
                )
                break
            except RuntimeError as exc:
                if "mps" in str(exc).lower() and not mps_retry and device == "mps":
                    device = handle_mps_instability(state)
                    save_state(state, state_path)
                    mps_retry = True
                    log.warning("Retrying on CPU after MPS failure …")
                else:
                    raise

        # Extract and log training metrics from this chunk
        history = results.get("history", {})
        chunk_losses = history.get("loss", [])
        all_losses.extend(chunk_losses)

        # Log per step (sampled at interval)
        for i, loss_val in enumerate(chunk_losses):
            step_counter += 1
            if step_counter % log_interval == 0:
                components = {
                    k: history[k][i] if k in history and i < len(history[k]) else 0.0
                    for k in ["reconstruction", "archetypal", "diversity", "regularity", "sparsity", "manifold"]
                }
                log_training_step(
                    step=step_counter,
                    epoch=chunk_start + i + 1,
                    loss_total=float(loss_val),
                    loss_components=components,
                )

        # Loss divergence check (Tier-1)
        tier1_cfg = getattr(config, "tier1", None)
        div_multiplier = float(getattr(tier1_cfg, "loss_divergence_multiplier", 2.0)) if tier1_cfg else 2.0
        div_window = int(getattr(tier1_cfg, "loss_divergence_window", 50)) if tier1_cfg else 50

        if check_loss_divergence(all_losses, multiplier=div_multiplier, window=div_window):
            # Only Tier-1 if it persists for two consecutive intervals (log on first)
            log.warning(f"Loss divergence detected at epoch {chunk_end}")
            record_tier2_event(
                state, "loss_spike",
                f"Loss spike at epoch {chunk_end}: {all_losses[-1]:.4f} (watching for persistence)"
            )

        # Save checkpoint
        ckpt_path = save_checkpoint(
            adata, results, chunk_end, checkpoint_base,
            max_to_keep=max_to_keep,
        )
        state.checkpoint_path = str(ckpt_path)
        save_state(state, state_path)
        log.info(f"Epoch {chunk_end}/{total_epochs} done; checkpoint saved")

    log.info(f"Training complete: {total_epochs} epochs, final loss = {all_losses[-1]:.4f}" if all_losses else "Training complete")
    _check_pcha_not_collapsed(adata, state, state_path, checkpoint_base)

    return adata, results


def _check_pcha_not_collapsed(adata: Any, state: RunState, state_path: Path, checkpoint_base: Path) -> None:
    """Tier-1: PCHA init failed if archetype coordinates are all-equal."""
    import numpy as np
    from peach_loop.ops.tier1 import raise_tier1, Tier1Condition

    coords_key = "X_archetypal"
    if "obsm" not in dir(adata) or coords_key not in adata.obsm:
        return  # can't check if not yet assigned

    coords = adata.obsm[coords_key]
    var = float(np.var(coords))
    if var < PCHA_DEGENERATE_THRESHOLD:
        raise_tier1(
            Tier1Condition.PCHA_INIT_FAILED,
            f"Archetype coordinates have near-zero variance ({var:.2e}) — PCHA warm start likely collapsed",
            state, state_path,
            checkpoint_base.parent.parent / "logs",
            extra={"coords_variance": var},
        )
