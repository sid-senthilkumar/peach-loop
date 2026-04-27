"""Phase 2 orchestration — sweep execution.

Runs all preprocessing variants with multiple seeds, accumulates results,
generates the comparison report, then halts at CP2.
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

log = get_logger("phase2.run")


def run_phase2(
    base_config: Config,
    sweep_config: Config,
    state: RunState,
    state_path: Path,
    n_archetypes: int,
) -> RunState:
    """Execute Phase 2 sweep.

    n_archetypes: the value determined in Phase 1 (held fixed across variants).
    sweep_config: loaded from configs/phase2/sweep.yaml.
    """
    from peach_loop.phase1.dataset import download_pbmc3k
    from peach_loop.phase2.variants import get_variants_from_config, apply_variant_preprocessing
    from peach_loop.phase2.sweep import run_variant_seed, compute_stability_metric, compute_archetype_correspondence
    from peach_loop.phase2.compare import generate_comparison_report

    log_dir = resolve_path(base_config, "logs")
    setup_logging(log_dir / "events", level=getattr(getattr(base_config, "logging", base_config), "level", "INFO"))

    state.current_phase = 2
    if state.phase_status not in ("running",):
        state.phase_status = "running"
        state.phase_start_time = datetime.now(timezone.utc).isoformat()
    save_state(state, state_path)

    raw_dir = resolve_path(base_config, "raw_data")
    sweep_output_dir = base_config.paths.reports and resolve_path(base_config, "phase2_report") or Path("reports/phase2")
    sweep_output_dir.mkdir(parents=True, exist_ok=True)
    digest_dir = resolve_path(base_config, "digests")
    digest_schedule = int(getattr(getattr(base_config, "digest", base_config), "schedule_hour", 8))

    # Hard caps
    total_cap_sec = float(getattr(sweep_config, "wall_clock_cap_hours", 48)) * 3600
    per_variant_cap_sec = float(getattr(sweep_config, "per_variant_cap_hours", 2)) * 3600
    per_seed_cap_sec = float(getattr(sweep_config, "per_seed_cap_minutes", 45)) * 60

    seeds = list(getattr(sweep_config, "seeds", [42, 123, 7]))
    peach_cfg = getattr(sweep_config, "peach", None)
    n_epochs = int(getattr(peach_cfg, "n_epochs", 150)) if peach_cfg else 150

    from peach_loop.phase1.train import select_device
    device = select_device(getattr(peach_cfg, "device", "auto") if peach_cfg else "auto")

    # Load raw data once
    log.info("Loading raw PBMC 3K for Phase 2 sweep …")
    adata_raw = download_pbmc3k(base_config, raw_dir)

    variants = get_variants_from_config(sweep_config)
    log.info(f"Sweep: {len(variants)} variants × {len(seeds)} seeds = {len(variants) * len(seeds)} total runs")

    all_results: dict[str, list[dict]] = {}
    stability_scores: dict[str, float] = {}
    phase_start = time.monotonic()

    for variant_cfg in variants:
        variant_name = getattr(variant_cfg, "name", "unnamed")
        variant_start = time.monotonic()

        # Disk check before each variant
        is_critical, disk_pct = check_disk_usage(raw_dir, 90)
        if is_critical:
            raise_tier1(Tier1Condition.DISK_CRITICAL, f"Disk {disk_pct:.1f}%", state, state_path, log_dir)

        # Total cap check
        if (time.monotonic() - phase_start) > total_cap_sec:
            state.phase_status = "cap_hit"
            save_state(state, state_path)
            log.warning("Phase 2 total wall-clock cap hit — stopping sweep")
            break

        log.info(f"=== Variant: {variant_name} ===")
        variant_results: list[dict] = []

        # Preprocess once for this variant (all seeds share the same preprocessed data)
        try:
            adata_preprocessed = apply_variant_preprocessing(adata_raw, variant_cfg)
        except Exception as exc:
            log.error(f"Preprocessing failed for variant '{variant_name}': {exc}")
            all_results[variant_name] = [{"variant_name": variant_name, "status": f"preprocessing_failed: {exc}"}]
            continue

        for seed in seeds:
            # Per-variant cap check
            if (time.monotonic() - variant_start) > per_variant_cap_sec:
                log.warning(f"Variant '{variant_name}' hit per-variant cap — moving to next variant")
                break

            result = run_variant_seed(
                adata_preprocessed=adata_preprocessed,
                variant_cfg=variant_cfg,
                seed=seed,
                n_archetypes=n_archetypes,
                n_epochs=n_epochs,
                device=device,
                cap_seconds=per_seed_cap_sec,
                output_dir=sweep_output_dir / "runs",
            )
            variant_results.append(result)

            if is_digest_due(state, digest_schedule):
                n_done = sum(len(v) for v in all_results.values()) + len(variant_results)
                generate_digest(state, base_config, digest_dir, extra_context={
                    "last_24h_summary": f"Sweep in progress: variant '{variant_name}', seed {seed}.",
                    "runs_completed": n_done,
                })
                save_state(state, state_path)

        all_results[variant_name] = variant_results

        # Stability metric for this variant
        completed_seeds = [r for r in variant_results if r.get("status") == "complete"]
        if len(completed_seeds) >= 2:
            cmp_cfg = getattr(sweep_config, "comparison", None)
            top_k = int(getattr(cmp_cfg, "top_k_cells_for_jaccard", 50)) if cmp_cfg else 50
            stability_scores[variant_name] = compute_stability_metric(completed_seeds, top_k=top_k)
        else:
            stability_scores[variant_name] = float("nan")

        log.info(f"Variant '{variant_name}' done; stability={stability_scores[variant_name]:.3f}" if stability_scores[variant_name] == stability_scores[variant_name] else f"Variant '{variant_name}' done; stability=N/A")

    # Archetype correspondence matrices (all pairs)
    correspondence_matrices: dict[tuple[str, str], list[list[float]]] = {}
    variant_names_completed = [n for n, v in all_results.items() if any(r.get("status") == "complete" for r in v)]
    for i in range(len(variant_names_completed)):
        for j in range(i + 1, len(variant_names_completed)):
            na, nb = variant_names_completed[i], variant_names_completed[j]
            mat = compute_archetype_correspondence(
                [r for r in all_results[na] if r.get("status") == "complete"],
                [r for r in all_results[nb] if r.get("status") == "complete"],
            )
            correspondence_matrices[(na, nb)] = mat

    # Save raw results JSON
    raw_results_path = sweep_output_dir / "all_results.json"
    with open(raw_results_path, "w") as f:
        json.dump(
            {k: [{kk: vv for kk, vv in r.items() if not kk.startswith("_")} for r in v] for k, v in all_results.items()},
            f, indent=2, default=str,
        )

    # Comparison report
    report_path = generate_comparison_report(
        all_results=all_results,
        stability_scores=stability_scores,
        correspondence_matrices={str(k): v for k, v in correspondence_matrices.items()},
        config=sweep_config,
        output_dir=sweep_output_dir,
    )
    state.phase2_report_path = str(report_path)
    if state.phase_status != "cap_hit":
        state.phase_status = "complete"
    save_state(state, state_path)

    # Final Phase 2 digest
    generate_digest(state, base_config, digest_dir, extra_context={
        "last_24h_summary": f"Phase 2 complete. {len(all_results)} variants. Report at {report_path}.",
        "runs_completed": sum(len(v) for v in all_results.values()),
        "forecast": "Waiting for CP2 human review before Phase 3.",
    })
    save_state(state, state_path)

    log.info(f"Phase 2 complete. Report: {report_path}")
    return state
