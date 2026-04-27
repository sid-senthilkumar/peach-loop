"""Smoke tests for report generators (Phase 1 and Phase 2 comparison)."""

import sys
import tempfile
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_synthetic_adata(n_cells=60, n_genes=30, n_pcs=10, n_archetypes=3):
    """Return a minimal AnnData with the fields PEACH would populate."""
    import anndata, pandas as pd

    rng = np.random.default_rng(0)
    X = rng.standard_normal((n_cells, n_genes)).astype("float32")
    adata = anndata.AnnData(X=X)
    adata.obsm["X_pca"] = rng.standard_normal((n_cells, n_pcs)).astype("float32")

    # Simulate post-training obs columns
    adata.obs["archetype"] = pd.Categorical(
        [str(i % n_archetypes) for i in range(n_cells)]
    )
    adata.obsm["X_archetypal"] = rng.dirichlet(
        np.ones(n_archetypes), size=n_cells
    ).astype("float32")

    # Simulate adata.uns enrichment structure
    adata.uns["peach_gene_assoc"] = {
        str(k): pd.DataFrame({
            "gene": [f"GENE{i}" for i in range(20)],
            "fdr": rng.uniform(0, 0.1, 20),
            "logfc": rng.uniform(0.1, 2.0, 20),
        })
        for k in range(n_archetypes)
    }
    return adata


def _make_fake_results(n_epochs=30):
    """Return a fake PEACH TrainingResults-like dict."""
    rng = np.random.default_rng(1)
    losses = list(np.linspace(2.0, 0.5, n_epochs) + rng.uniform(-0.05, 0.05, n_epochs))
    return {
        "history": {
            "loss": losses,
            "reconstruction": [l * 0.7 for l in losses],
            "archetypal":     [l * 0.1 for l in losses],
            "diversity":      [l * 0.05 for l in losses],
            "regularity":     [l * 0.05 for l in losses],
            "sparsity":       [l * 0.05 for l in losses],
            "manifold":       [l * 0.05 for l in losses],
        },
        "final_archetype_r2": 0.82,
        "best_epoch": n_epochs,
        "n_archetypes": 3,
    }


def _make_config():
    from peach_loop.config import load_config
    return load_config(
        str(Path(__file__).parent.parent / "configs" / "base.yaml"),
        str(Path(__file__).parent.parent / "configs" / "phase1.yaml"),
    )


# ── Phase 1 report ─────────────────────────────────────────────────────────────

def test_phase1_report_generates_file(tmp_path):
    """Phase 1 report is written and contains key sections."""
    from peach_loop.phase1.report import generate_phase1_report
    from peach_loop.ops.state import RunState

    cfg = _make_config()
    adata = _make_synthetic_adata()
    results = _make_fake_results()
    eval_metrics = {
        "final_archetype_r2": 0.82,
        "test_reconstruction_loss": 0.55,
        "assignment_counts": {"0": 20, "1": 20, "2": 20},
        "n_archetypes": 3,
    }
    enrichment = {
        "soft_criterion": {"0": {"n_sig": 5, "passes": True}, "1": {"n_sig": 2, "passes": False}},
        "marker_check": {"T_cell": {"markers": ["CD3D"], "best_archetype": "0", "overlap_count": 1}},
    }
    state = RunState(current_phase=1, phase_status="complete", phase1_n_archetypes=3, phase1_archetype_r2=0.82)

    report_path = generate_phase1_report(
        adata=adata,
        results=results,
        eval_metrics=eval_metrics,
        enrichment_results=enrichment,
        config=cfg,
        state=state,
        output_dir=tmp_path,
        dataset_meta={"source": "test", "n_cells": 60, "n_genes": 30, "sha256": "abc123", "download_ts": "2025-01-01"},
    )

    assert report_path.exists()
    content = report_path.read_text()
    for section in ["Dataset", "Preprocessing", "Training", "Evaluation", "Enrichment", "Acceptance"]:
        assert section in content, f"Report missing section: {section}"
    assert "0.8200" in content  # R² value appears
    assert "PASS" in content    # at least one PASS


def test_phase1_report_handles_missing_results(tmp_path):
    """Phase 1 report generates without error even when results are sparse."""
    from peach_loop.phase1.report import generate_phase1_report
    from peach_loop.ops.state import RunState

    cfg = _make_config()
    adata = _make_synthetic_adata()
    state = RunState(current_phase=1, phase_status="complete")

    report_path = generate_phase1_report(
        adata=adata,
        results={},  # empty
        eval_metrics={},
        enrichment_results={},
        config=cfg,
        state=state,
        output_dir=tmp_path,
    )
    assert report_path.exists()


# ── Phase 2 comparison report ───────────────────────────────────────────────────

def _make_fake_sweep_results():
    """Return a minimal all_results dict for comparison report testing."""
    rng = np.random.default_rng(2)
    variants = ["log_norm_hvg2000", "log_norm_hvg1000", "raw_counts"]
    all_results = {}
    for name in variants:
        seeds_results = []
        for seed in [42, 123, 7]:
            losses = list(np.linspace(2.0 + rng.uniform(0, 0.5), 0.5 + rng.uniform(0, 0.3), 20))
            seeds_results.append({
                "variant_name": name,
                "seed": seed,
                "n_archetypes": 3,
                "final_loss": losses[-1],
                "final_archetype_r2": float(rng.uniform(0.6, 0.9)),
                "loss_history": losses,
                "archetype_assignments": {"0": 20, "1": 20, "2": 20},
                "enrichment_top3": {"0": ["GENE1", "GENE2"], "1": ["GENE3"]},
                "elapsed_seconds": 30.0,
                "status": "complete",
                "_archetype_obs": {f"cell_{i}": str(i % 3) for i in range(60)},
            })
        all_results[name] = seeds_results
    return all_results


def test_comparison_report_generates(tmp_path):
    """Comparison report is written and contains required sections."""
    from peach_loop.phase2.compare import generate_comparison_report
    from peach_loop.config import load_config

    sweep_cfg = load_config(
        str(Path(__file__).parent.parent / "configs" / "base.yaml"),
        str(Path(__file__).parent.parent / "configs" / "phase2" / "sweep.yaml"),
    )
    all_results = _make_fake_sweep_results()
    stability = {name: 0.7 for name in all_results}
    correspondence = {}

    report_path = generate_comparison_report(
        all_results=all_results,
        stability_scores=stability,
        correspondence_matrices=correspondence,
        config=sweep_cfg,
        output_dir=tmp_path,
    )
    assert report_path.exists()
    content = report_path.read_text()
    for section in ["Per-Variant", "Loss", "Stability", "Acceptance"]:
        assert section in content, f"Comparison report missing section: {section}"


def test_stability_metric_value():
    """compute_stability_metric returns a float in [0, 1] for valid inputs."""
    from peach_loop.phase2.sweep import compute_stability_metric

    results = [
        {"_archetype_obs": {f"cell_{i}": str(i % 3) for i in range(60)}, "status": "complete"},
        {"_archetype_obs": {f"cell_{i}": str(i % 3) for i in range(60)}, "status": "complete"},
    ]
    score = compute_stability_metric(results, top_k=10)
    # Identical assignments → Jaccard = 1.0
    assert 0.0 <= score <= 1.0, f"Stability score out of range: {score}"
    assert abs(score - 1.0) < 0.01, "Identical assignments should give stability ≈ 1.0"


def test_stability_metric_nan_for_single_seed():
    """compute_stability_metric returns NaN when only one seed is provided."""
    import math
    from peach_loop.phase2.sweep import compute_stability_metric

    results = [{"_archetype_obs": {"cell_0": "0"}, "status": "complete"}]
    score = compute_stability_metric(results)
    assert math.isnan(score), "Single-seed stability should be NaN"
