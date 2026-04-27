"""Phase 1 orchestration.

Runs the full Phase 1 pipeline end-to-end:
  1. Download + preprocess dataset
  2. Hyperparameter search (unless n_archetypes fixed in config)
  3. Train with checkpointing (resume if checkpoint exists)
  4. Post-training: archetypal_coordinates, assign_archetypes
  5. Held-out evaluation
  6. Gene/pathway enrichment
  7. Generate report + 3D plot
  8. Generate daily digest if due

Called by scripts/run_all.py.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peach_loop.config import Config, resolve_path
from peach_loop.ops.logger import get_logger, setup_logging
from peach_loop.ops.state import RunState, save_state, phase_elapsed_seconds
from peach_loop.ops.digest import is_digest_due, generate_digest
from peach_loop.ops.tier1 import check_disk_usage, raise_tier1, Tier1Condition
from peach_loop.ops.tier2 import handle_disk_warning

log = get_logger("phase1.run")


def run_phase1(config: Config, state: RunState, state_path: Path) -> RunState:
    """Execute Phase 1 from start (or resume from checkpoint).

    Modifies state in place; saves state frequently.
    Returns state with phase_status = "complete" or "cap_hit".
    """
    from peach_loop.phase1.dataset import download_pbmc3k, preprocess_adata, train_test_split_adata
    from peach_loop.phase1.train import select_device, run_hyperparameter_search, train_with_checkpoints
    from peach_loop.phase1.evaluate import evaluate_model
    from peach_loop.phase1.enrichment import run_enrichment
    from peach_loop.phase1.report import generate_phase1_report
    import peach as pc

    log_dir = resolve_path(config, "logs")
    setup_logging(log_dir / "events", level=getattr(getattr(config, "logging", config), "level", "INFO"))

    state.current_phase = 1
    if state.phase_status not in ("running", "cap_hit"):
        state.phase_status = "running"
        state.phase_start_time = datetime.now(timezone.utc).isoformat()
    save_state(state, state_path)

    raw_dir = resolve_path(config, "raw_data")
    processed_dir = resolve_path(config, "processed_data")
    checkpoint_base = resolve_path(config, "checkpoints") / "phase1"
    report_dir = resolve_path(config, "phase1_report")
    digest_dir = resolve_path(config, "digests")
    digest_schedule = int(getattr(getattr(config, "digest", config), "schedule_hour", 8))

    # ── Disk check ──────────────────────────────────────────────────────────
    tier1_cfg = getattr(config, "tier1", None)
    disk_critical = float(getattr(tier1_cfg, "disk_usage_critical_pct", 90)) if tier1_cfg else 90
    tier2_cfg = getattr(config, "tier2", None)
    disk_warn = float(getattr(tier2_cfg, "disk_usage_warning_pct", 80)) if tier2_cfg else 80

    is_critical, disk_pct = check_disk_usage(raw_dir, disk_critical)
    if is_critical:
        raise_tier1(Tier1Condition.DISK_CRITICAL, f"Disk {disk_pct:.1f}%", state, state_path, log_dir)
    if disk_pct > disk_warn:
        handle_disk_warning(state, checkpoint_base, disk_pct)
        save_state(state, state_path)

    # ── Step 1: Dataset ──────────────────────────────────────────────────────
    log.info("=== Phase 1 Step 1: Dataset acquisition ===")
    adata_raw = download_pbmc3k(config, raw_dir)

    # Load download metadata for report
    meta_path = raw_dir / "pbmc3k_download_meta.json"
    dataset_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    if is_digest_due(state, digest_schedule):
        generate_digest(state, config, digest_dir, extra_context={"last_24h_summary": "Dataset downloaded."})
        save_state(state, state_path)

    # ── Step 2: Preprocessing ────────────────────────────────────────────────
    log.info("=== Phase 1 Step 2: Preprocessing ===")

    # Check for existing processed checkpoint
    latest_ckpt = _find_latest_checkpoint(checkpoint_base)
    if latest_ckpt:
        from peach_loop.ops.checkpoint import load_checkpoint
        log.info(f"Resuming from checkpoint: {latest_ckpt}")
        adata_train, ckpt_meta = load_checkpoint(latest_ckpt)
        start_epoch = int(ckpt_meta.get("epoch", 0))
        adata_test = _load_test_split(processed_dir, adata_raw, config)
        n_archetypes = int(state.phase1_n_archetypes or ckpt_meta.get("n_archetypes", 5))
        results_placeholder = {}
    else:
        start_epoch = 0
        adata_preprocessed = preprocess_adata(adata_raw, config)
        adata_train, adata_test = train_test_split_adata(
            adata_preprocessed,
            train_frac=float(getattr(getattr(config, "peach", config), "train_test_split", 0.8)),
            seed=int(getattr(getattr(config, "peach", config), "random_seed", 42)),
        )
        # Save test split for resume
        adata_test.write_h5ad(processed_dir / "adata_test.h5ad")
        adata_train.write_h5ad(processed_dir / "adata_train_preprocessed.h5ad")

        # ── Step 3: Hyperparameter search ─────────────────────────────────
        log.info("=== Phase 1 Step 3: Hyperparameter search ===")
        peach_cfg = getattr(config, "peach", config)
        n_archetypes_cfg = getattr(peach_cfg, "n_archetypes", None)

        if n_archetypes_cfg is None:
            n_archetypes = run_hyperparameter_search(adata_train, config)
        else:
            n_archetypes = int(n_archetypes_cfg)
            log.info(f"Using configured n_archetypes = {n_archetypes} (skipping search)")

        state.phase1_n_archetypes = n_archetypes
        save_state(state, state_path)
        results_placeholder = {}

    if is_digest_due(state, digest_schedule):
        generate_digest(state, config, digest_dir, extra_context={
            "last_24h_summary": f"Preprocessing done; n_archetypes={n_archetypes}."
        })
        save_state(state, state_path)

    # ── Step 4: Training ─────────────────────────────────────────────────────
    log.info(f"=== Phase 1 Step 4: Training (start_epoch={start_epoch}) ===")
    adata_trained, results = train_with_checkpoints(
        adata=adata_train,
        n_archetypes=n_archetypes,
        config=config,
        checkpoint_base=checkpoint_base,
        state=state,
        state_path=state_path,
        start_epoch=start_epoch,
    )

    if is_digest_due(state, digest_schedule):
        history = results.get("history", {})
        losses = history.get("loss", [])
        generate_digest(state, config, digest_dir, extra_context={
            "last_24h_summary": "Training complete.",
            "current_loss": f"{losses[-1]:.4f}" if losses else "N/A",
            "runs_completed": 1,
        })
        save_state(state, state_path)

    # ── Step 5: Post-training assignments ────────────────────────────────────
    log.info("=== Phase 1 Step 5: Archetypal coordinates and assignments ===")
    try:
        pc.tl.archetypal_coordinates(adata_trained)
        pc.tl.assign_archetypes(
            adata_trained,
            percentage_per_archetype=float(
                getattr(getattr(config, "enrichment", config), "archetype_assignment_pct", 0.15)
            ),
        )
    except Exception as exc:
        log.warning(f"Archetype assignment step failed: {exc}")

    # ── Step 6: Evaluation ───────────────────────────────────────────────────
    log.info("=== Phase 1 Step 6: Evaluation ===")
    # Reload test split (may have been loaded from disk on resume)
    if not hasattr(adata_test, "n_obs"):
        adata_test = _load_test_split(processed_dir, adata_raw, config)

    eval_metrics = evaluate_model(adata_trained, adata_test, results, config)
    r2 = eval_metrics.get("final_archetype_r2")
    state.phase1_archetype_r2 = r2
    save_state(state, state_path)

    # ── Step 7: Enrichment ───────────────────────────────────────────────────
    log.info("=== Phase 1 Step 7: Gene/pathway enrichment ===")
    enrichment_results = run_enrichment(adata_trained, config)

    # ── Step 8: Report ───────────────────────────────────────────────────────
    log.info("=== Phase 1 Step 8: Report generation ===")
    report_path = generate_phase1_report(
        adata=adata_trained,
        results=results,
        eval_metrics=eval_metrics,
        enrichment_results=enrichment_results,
        config=config,
        state=state,
        output_dir=report_dir,
        dataset_meta=dataset_meta,
    )
    state.phase1_report_path = str(report_path)
    state.phase_status = "complete"
    save_state(state, state_path)

    # Final digest for Phase 1
    history = results.get("history", {})
    losses = history.get("loss", [])
    generate_digest(state, config, digest_dir, extra_context={
        "last_24h_summary": f"Phase 1 complete. Report at {report_path}.",
        "current_loss": f"{losses[-1]:.4f}" if losses else "N/A",
        "eval_results": f"R²={r2:.4f}" if r2 is not None else "N/A",
        "runs_completed": 1,
        "forecast": "Waiting for CP1 human review before Phase 2.",
        "plot_path": str(report_dir / "loss_curves.png"),
    })
    save_state(state, state_path)

    log.info(f"Phase 1 complete. Report: {report_path}")
    return state


def _find_latest_checkpoint(checkpoint_base: Path):
    from peach_loop.ops.checkpoint import get_latest_checkpoint
    return get_latest_checkpoint(checkpoint_base)


def _load_test_split(processed_dir: Path, adata_raw: Any, config: Any) -> Any:
    """Load test split from disk, or re-split if not found."""
    import anndata
    from peach_loop.phase1.dataset import preprocess_adata, train_test_split_adata

    test_path = processed_dir / "adata_test.h5ad"
    if test_path.exists():
        return anndata.read_h5ad(test_path)

    log.warning("Test split not found on disk — re-splitting from raw data")
    adata_pp = preprocess_adata(adata_raw, config)
    peach_cfg = getattr(config, "peach", config)
    _, adata_test = train_test_split_adata(
        adata_pp,
        train_frac=float(getattr(peach_cfg, "train_test_split", 0.8)),
        seed=int(getattr(peach_cfg, "random_seed", 42)),
    )
    return adata_test
