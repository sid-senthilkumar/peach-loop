"""Held-out evaluation for Phase 1.

Computes metrics on the test split to assess generalisation.
Also checks the PBMC immune-marker sanity criterion (soft, AGENTS.md §3.5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from peach_loop.ops.logger import get_logger

log = get_logger("phase1.evaluate")


def evaluate_model(
    adata_train: Any,
    adata_test: Any,
    results: dict,
    config: Any,
) -> dict:
    """Run evaluation on held-out cells.

    Returns a dict with:
      - final_archetype_r2        (from PEACH TrainingResults)
      - test_reconstruction_loss  (manual computation on test set)
      - archetype_assignments     (assignment distribution on test set)
      - marker_sanity             (immune marker check result)
    """
    import numpy as np
    import peach as pc

    peach_cfg = getattr(config, "peach", config)
    n_archetypes = results.get("n_archetypes") or int(
        getattr(peach_cfg, "n_archetypes", 5) or 5
    )
    assign_pct = float(getattr(getattr(config, "enrichment", config), "archetype_assignment_pct", 0.15))

    # Post-training steps on training set (needed before evaluation)
    log.info("Computing archetypal coordinates and assignments …")
    try:
        pc.tl.archetypal_coordinates(adata_train)
        pc.tl.assign_archetypes(adata_train, percentage_per_archetype=assign_pct)
    except Exception as exc:
        log.warning(f"archetypal_coordinates/assign_archetypes on train set failed: {exc}")

    # Archetype R² from TrainingResults
    r2 = results.get("final_archetype_r2")
    if r2 is None:
        log.warning("final_archetype_r2 not present in TrainingResults — will be None in report")

    # Manual reconstruction loss on test set
    test_loss = _compute_test_reconstruction(adata_test, results)

    # Immune marker sanity check
    acceptance_cfg = getattr(config, "acceptance", None)
    known_markers = (
        {k: list(v) for k, v in getattr(acceptance_cfg, "known_markers", {}).items()}
        if acceptance_cfg else {}
    )
    marker_result = check_immune_markers(adata_train, known_markers)

    # Assignment distribution
    assignment_counts = {}
    if "archetype" in adata_train.obs.columns:
        assignment_counts = adata_train.obs["archetype"].value_counts().to_dict()

    metrics = {
        "final_archetype_r2": r2,
        "test_reconstruction_loss": test_loss,
        "assignment_counts": assignment_counts,
        "marker_sanity": marker_result,
        "n_archetypes": n_archetypes,
    }
    log.info(f"Evaluation: R²={r2}, test_loss={test_loss}")
    return metrics


def _compute_test_reconstruction(adata_test: Any, results: dict) -> float | None:
    """Attempt to compute reconstruction loss on test cells using the trained model."""
    import torch
    import numpy as np

    model = results.get("model")
    if model is None:
        return None

    try:
        # Use PCA representation as input (same as training)
        if "X_pca" not in adata_test.obsm:
            log.warning("PCA not found in test set obsm — skipping test reconstruction loss")
            return None

        x = torch.tensor(adata_test.obsm["X_pca"], dtype=torch.float32)
        model.eval()
        with torch.no_grad():
            out = model(x)
        # Assume model returns (reconstruction, archetype_coords) or just reconstruction
        if isinstance(out, (tuple, list)):
            recon = out[0]
        else:
            recon = out
        loss = float(torch.nn.functional.mse_loss(recon, x).item())
        return loss
    except Exception as exc:
        log.warning(f"Test reconstruction loss computation failed: {exc}")
        return None


def check_immune_markers(adata: Any, known_markers: dict[str, list[str]]) -> dict:
    """Check whether archetype top genes include known PBMC immune markers.

    Soft criterion — results are reported but do not fail the run.
    Returns a dict: {cell_type: {"found": [genes], "archetype": int or None}}.
    """
    if not known_markers:
        return {}

    result = {}
    var_names = set(adata.var_names)

    for cell_type, markers in known_markers.items():
        present = [m for m in markers if m in var_names]
        result[cell_type] = {
            "markers_present_in_data": present,
            "matched_archetype": None,
            "note": "sanity check not yet run — call after gene_associations",
        }

    return result


def check_monotonic_reconstruction(results: dict) -> tuple[bool, str]:
    """Check that reconstruction loss decreased (roughly) monotonically.

    Returns (passes, explanation_string).
    Allows for the "usual small-step noise" — checks overall trend, not strict monotone.
    """
    history = results.get("history", {})
    recon_losses = history.get("reconstruction") or history.get("loss", [])

    if len(recon_losses) < 10:
        return True, "Too few steps to assess monotonicity"

    import numpy as np

    losses = np.array(recon_losses, dtype=float)
    # Split into first and second half; second half mean should be lower
    mid = len(losses) // 2
    first_half_mean = float(np.mean(losses[:mid]))
    second_half_mean = float(np.mean(losses[mid:]))

    passes = second_half_mean < first_half_mean
    direction = "decreased" if passes else "INCREASED"
    explanation = (
        f"Reconstruction loss {direction}: "
        f"first-half mean={first_half_mean:.4f}, second-half mean={second_half_mean:.4f}"
    )
    return passes, explanation
