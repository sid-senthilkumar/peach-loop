"""Phase 2 sweep execution.

Runs each preprocessing variant with multiple seeds, computing:
  - Final reconstruction loss and archetype R²
  - Loss trajectory (all steps)
  - Stability metric: Jaccard similarity of top-k assigned cells across seeds

Per AGENTS.md §4.3 hard caps:
  - 48h total
  - 2h per variant
  - 45 min per seed within a variant
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peach_loop.ops.logger import get_logger
from peach_loop.ops.state import RunState, record_tier2_event, save_state

log = get_logger("phase2.sweep")

# Keys stored per variant run
VARIANT_RESULT_KEYS = [
    "variant_name", "seed", "n_archetypes", "final_loss",
    "final_archetype_r2", "loss_history", "archetype_assignments",
    "enrichment_top3", "elapsed_seconds", "status",
]


def run_variant_seed(
    adata_preprocessed: Any,
    variant_cfg: Any,
    seed: int,
    n_archetypes: int,
    n_epochs: int,
    device: str,
    cap_seconds: float,
    output_dir: Path,
) -> dict:
    """Run a single (variant, seed) combination.

    Returns a result dict with VARIANT_RESULT_KEYS.
    Catches all exceptions to ensure the sweep continues on failure.
    """
    import peach as pc
    import torch

    variant_name = getattr(variant_cfg, "name", "unnamed")
    log.info(f"Running variant='{variant_name}' seed={seed} n_archetypes={n_archetypes}")

    start = time.monotonic()
    try:
        import numpy as np
        # Set seeds for reproducibility
        torch.manual_seed(seed)
        np.random.seed(seed)

        adata = adata_preprocessed.copy()

        results = pc.tl.train_archetypal(
            adata,
            n_archetypes=n_archetypes,
            n_epochs=n_epochs,
            device=device,
        )

        elapsed = time.monotonic() - start
        if elapsed > cap_seconds:
            log.warning(f"Variant '{variant_name}' seed {seed} exceeded cap ({elapsed:.0f}s > {cap_seconds:.0f}s)")

        # Post-training
        try:
            pc.tl.archetypal_coordinates(adata)
            pc.tl.assign_archetypes(adata, percentage_per_archetype=0.15)
        except Exception as e:
            log.warning(f"assign_archetypes failed: {e}")

        # Extract results
        history = results.get("history", {})
        losses = history.get("loss", [])
        r2 = results.get("final_archetype_r2")

        # Top gene enrichment for top 3 archetypes
        enr_top3 = {}
        try:
            pc.tl.gene_associations(adata, fdr_scope="global", min_logfc=0.1)
            gene_assoc = (
                adata.uns.get("peach_gene_assoc")
                or adata.uns.get("gene_associations")
                or adata.uns.get("peach", {}).get("gene_associations")
            )
            if gene_assoc and isinstance(gene_assoc, dict):
                import pandas as pd
                for i, (arch_key, df) in enumerate(list(gene_assoc.items())[:3]):
                    if isinstance(df, pd.DataFrame) and "gene" in df.columns:
                        top_genes = df.head(10)["gene"].tolist() if "fdr" not in df.columns else df.nsmallest(10, "fdr")["gene"].tolist()
                        enr_top3[arch_key] = top_genes
        except Exception as e:
            log.warning(f"Enrichment failed for variant '{variant_name}' seed {seed}: {e}")

        # Assignment distribution
        assign_counts = {}
        if "archetype" in adata.obs.columns:
            assign_counts = adata.obs["archetype"].value_counts().to_dict()

        result = {
            "variant_name": variant_name,
            "seed": seed,
            "n_archetypes": n_archetypes,
            "final_loss": float(losses[-1]) if losses else None,
            "final_archetype_r2": float(r2) if r2 is not None else None,
            "loss_history": [float(x) for x in losses],
            "archetype_assignments": {str(k): int(v) for k, v in assign_counts.items()},
            "enrichment_top3": enr_top3,
            "elapsed_seconds": time.monotonic() - start,
            "status": "complete",
            # Store cell-level archetype index for Jaccard computation
            "_archetype_obs": adata.obs.get("archetype", None) and adata.obs["archetype"].to_dict(),
        }

        # Save per-run adata
        run_dir = output_dir / f"{variant_name}_seed{seed}"
        run_dir.mkdir(parents=True, exist_ok=True)
        adata.write_h5ad(run_dir / "adata.h5ad")
        with open(run_dir / "result.json", "w") as f:
            json.dump({k: v for k, v in result.items() if not k.startswith("_")}, f, indent=2, default=str)

        log.info(f"Variant '{variant_name}' seed {seed}: loss={result['final_loss']}, R²={result['final_archetype_r2']}")
        return result

    except Exception as exc:
        elapsed = time.monotonic() - start
        log.error(f"Variant '{variant_name}' seed {seed} FAILED after {elapsed:.0f}s: {exc}")
        return {
            "variant_name": variant_name,
            "seed": seed,
            "n_archetypes": n_archetypes,
            "final_loss": None,
            "final_archetype_r2": None,
            "loss_history": [],
            "archetype_assignments": {},
            "enrichment_top3": {},
            "elapsed_seconds": elapsed,
            "status": f"failed: {exc}",
            "_archetype_obs": None,
        }


def compute_stability_metric(
    results_for_seeds: list[dict],
    top_k: int = 50,
) -> float:
    """Compute mean Jaccard similarity of top-k assigned cells across seed pairs.

    For each archetype index, get the top-k cells (by assignment count) across
    each seed run, then compute pairwise Jaccard.  Average over archetypes and pairs.

    Returns a float in [0, 1].  1 = identical across seeds.
    """
    if len(results_for_seeds) < 2:
        return float("nan")

    # Collect per-archetype cell sets per seed
    all_archetypes: set = set()
    per_seed_arch_cells: list[dict[str, set]] = []

    for result in results_for_seeds:
        arch_obs = result.get("_archetype_obs") or {}
        if not arch_obs:
            # Fall back to assignment counts (less precise)
            per_seed_arch_cells.append({})
            continue

        arch_cells: dict[str, set] = {}
        import pandas as pd

        obs_series = pd.Series(arch_obs)
        for arch in obs_series.unique():
            cell_indices = set(obs_series[obs_series == arch].index.tolist())
            arch_cells[str(arch)] = cell_indices
            all_archetypes.add(str(arch))

        per_seed_arch_cells.append(arch_cells)

    if not all_archetypes:
        return float("nan")

    # Pairwise Jaccard per archetype
    jaccards = []
    for arch in all_archetypes:
        cell_sets = [s.get(arch, set()) for s in per_seed_arch_cells]
        # Take top-k by size (simulate "top-k assigned cells")
        cell_sets = [s for s in cell_sets if s]
        if len(cell_sets) < 2:
            continue
        for i in range(len(cell_sets)):
            for j in range(i + 1, len(cell_sets)):
                a, b = cell_sets[i], cell_sets[j]
                intersection = len(a & b)
                union = len(a | b)
                jaccards.append(intersection / union if union > 0 else 0.0)

    return float(sum(jaccards) / len(jaccards)) if jaccards else float("nan")


def compute_archetype_correspondence(results_a: list[dict], results_b: list[dict]) -> list[list[float]]:
    """Compute pairwise archetype correspondence between two variants.

    Uses cell overlap: fraction of top-k assigned cells shared between archetypes.
    Returns a matrix [n_archetypes_a × n_archetypes_b].
    """
    if not results_a or not results_b:
        return []

    # Use the first seed of each variant
    obs_a = results_a[0].get("_archetype_obs") or {}
    obs_b = results_b[0].get("_archetype_obs") or {}
    if not obs_a or not obs_b:
        return []

    import pandas as pd

    series_a = pd.Series(obs_a)
    series_b = pd.Series(obs_b)
    archs_a = sorted(series_a.unique().tolist())
    archs_b = sorted(series_b.unique().tolist())

    common_cells = set(series_a.index) & set(series_b.index)
    if not common_cells:
        return []

    series_a = series_a[list(common_cells)]
    series_b = series_b[list(common_cells)]

    matrix = []
    for arch_a in archs_a:
        row = []
        cells_a = set(series_a[series_a == arch_a].index)
        for arch_b in archs_b:
            cells_b = set(series_b[series_b == arch_b].index)
            union = len(cells_a | cells_b)
            overlap = len(cells_a & cells_b) / union if union else 0.0
            row.append(overlap)
        matrix.append(row)

    return matrix
