"""Phase 1 report generation.

Generates a markdown report summarising what happened, as required by AGENTS.md §3.1.
Also produces the 3D archetypal-space visualization as a static PNG.

Call generate_phase1_report() at the end of Phase 1.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peach_loop.ops.logger import get_logger

log = get_logger("phase1.report")


def generate_phase1_report(
    adata: Any,
    results: dict,
    eval_metrics: dict,
    enrichment_results: dict,
    config: Any,
    state: Any,
    output_dir: Path,
    dataset_meta: dict | None = None,
) -> Path:
    """Write Phase 1 markdown report to output_dir/phase1_report.md.

    Returns the report path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "phase1_report.md"

    plot_path = _render_3d_plot(adata, output_dir)
    loss_plot_path = _render_loss_curve(results, output_dir)

    monotonic_passes, monotonic_explanation = _check_monotone(results)
    r2 = eval_metrics.get("final_archetype_r2")
    acceptance_cfg = getattr(config, "acceptance", None)
    r2_min = float(getattr(acceptance_cfg, "archetype_r2_min", 0.7)) if acceptance_cfg else 0.7

    lines = [
        "# Phase 1 Report — PEACH Baseline Run",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "---",
        "",
        "## 1. Dataset",
        "",
    ]

    if dataset_meta:
        lines += [
            f"- **Source:** {dataset_meta.get('source', 'unknown')}",
            f"- **Download timestamp:** {dataset_meta.get('download_ts', 'unknown')}",
            f"- **Cells:** {dataset_meta.get('n_cells', adata.n_obs)}",
            f"- **Genes (raw):** {dataset_meta.get('n_genes', 'unknown')}",
            f"- **SHA-256:** `{dataset_meta.get('sha256', 'not recorded')}`",
        ]
    else:
        lines += [
            f"- **Cells (post-preprocessing):** {adata.n_obs}",
            f"- **Genes (post-HVG filter):** {adata.n_vars}",
        ]

    lines += [
        "",
        "## 2. Preprocessing",
        "",
    ]
    pp_cfg = getattr(config, "preprocessing", None)
    if pp_cfg:
        lines += [
            f"- Normalised to {getattr(pp_cfg, 'normalize_total_target', 1e4):.0f} counts/cell",
            f"- log1p transformed: {getattr(pp_cfg, 'log_transform', True)}",
            f"- Highly variable genes: {getattr(pp_cfg, 'n_highly_variable_genes', 2000)}",
            f"- Scaled: {getattr(pp_cfg, 'scale', True)}",
            f"- PCA components: {getattr(pp_cfg, 'pca_components', 50)}",
        ]

    peach_cfg = getattr(config, "peach", None)
    n_archetypes = eval_metrics.get("n_archetypes") or (int(getattr(peach_cfg, "n_archetypes", 5)) if peach_cfg else 5)

    lines += [
        "",
        "## 3. Training",
        "",
        f"- **n_archetypes:** {n_archetypes}",
        f"- **n_epochs:** {getattr(peach_cfg, 'n_epochs', 150) if peach_cfg else 150}",
        f"- **Device:** {results.get('device', 'unknown')}",
        f"- **Loss monotonicity:** {'✓ PASS' if monotonic_passes else '✗ FAIL'} — {monotonic_explanation}",
    ]

    history = results.get("history", {})
    all_losses = history.get("loss", [])
    if all_losses:
        lines += [
            f"- **Initial loss:** {all_losses[0]:.4f}",
            f"- **Final loss:** {all_losses[-1]:.4f}",
        ]

    if loss_plot_path:
        lines += [f"", f"![Loss curves]({loss_plot_path.name})"]

    lines += [
        "",
        "## 4. Evaluation",
        "",
        f"- **Archetype R²:** {r2:.4f if r2 is not None else 'N/A'} "
        f"(threshold: {r2_min}) — {'✓ PASS' if (r2 is not None and r2 >= r2_min) else '✗ FAIL or N/A'}",
        f"- **Test reconstruction loss:** {eval_metrics.get('test_reconstruction_loss', 'N/A')}",
        "",
        "### Archetype assignment distribution",
        "",
    ]
    counts = eval_metrics.get("assignment_counts", {})
    if counts:
        for arch, cnt in sorted(counts.items()):
            lines.append(f"- Archetype {arch}: {cnt} cells")
    else:
        lines.append("_Assignment counts not available._")

    lines += [
        "",
        "## 5. Gene Set Enrichment",
        "",
    ]
    soft = enrichment_results.get("soft_criterion", {})
    if soft:
        lines.append("### Soft criterion: ≥ 3 significant gene set associations per archetype (FDR < 0.05)")
        lines.append("")
        for arch_key, check in soft.items():
            icon = "✓" if check.get("passes") else "⚠"
            lines.append(f"- {icon} Archetype {arch_key}: {check.get('n_sig', 0)} significant associations")
    else:
        lines.append("_Enrichment results not available — see logs._")

    lines += [
        "",
        "### Immune marker sanity check (soft criterion)",
        "",
    ]
    markers = enrichment_results.get("marker_check", {})
    if markers:
        for cell_type, info in markers.items():
            arch = info.get("best_archetype", "none")
            overlap = info.get("overlap_count", 0)
            lines.append(f"- **{cell_type}:** {overlap} marker genes matched in archetype {arch}")
    else:
        lines.append("_Marker check not available._")

    lines += [
        "",
        "## 6. Acceptance Criteria Summary",
        "",
        f"| Criterion | Value | Threshold | Status |",
        f"|-----------|-------|-----------|--------|",
        f"| Archetype R² | {r2:.4f if r2 is not None else 'N/A'} | ≥ {r2_min} | {'PASS' if (r2 is not None and r2 >= r2_min) else 'FAIL'} |",
        f"| Loss monotone | {monotonic_explanation[:40]} | decreasing | {'PASS' if monotonic_passes else 'FAIL'} |",
        f"| Resume test | Run separately via `make test-resume` | — | — |",
        "",
        "## 7. 3D Archetypal Space",
        "",
    ]
    if plot_path:
        lines += [f"![Archetypal space]({plot_path.name})", ""]
    else:
        lines += ["_3D plot not generated — see logs._", ""]

    lines += [
        "## 8. Notes and Deviations",
        "",
        "_None noted. See `logs/decisions_pending.jsonl` for pending questions._",
        "",
    ]

    content = "\n".join(lines)
    with open(report_path, "w") as f:
        f.write(content)

    log.info(f"Phase 1 report written: {report_path}")
    return report_path


def _render_3d_plot(adata: Any, output_dir: Path) -> Path | None:
    """Render 3D archetypal space via PEACH and save as static PNG."""
    try:
        import peach as pc
        fig = pc.pl.archetypal_space(adata, color_by="archetypes")
        png_path = output_dir / "archetypal_space_3d.png"
        fig.write_image(str(png_path))
        log.info(f"3D plot saved: {png_path}")
        return png_path
    except Exception as exc:
        log.warning(f"3D plot generation failed: {exc}")
        return None


def _render_loss_curve(results: dict, output_dir: Path) -> Path | None:
    """Render loss curves (total + components) as a static PNG."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib

        matplotlib.use("Agg")  # non-interactive backend

        history = results.get("history", {})
        if not history:
            return None

        fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

        # Total loss
        if "loss" in history:
            axes[0].plot(history["loss"], label="Total", color="black", linewidth=2)
            axes[0].set_ylabel("Loss")
            axes[0].set_title("Training Loss — Total")
            axes[0].legend()

        # Component losses
        components = ["reconstruction", "archetypal", "diversity", "regularity", "sparsity", "manifold"]
        present = [c for c in components if c in history]
        colors = plt.cm.tab10.colors
        for i, comp in enumerate(present):
            axes[1].plot(history[comp], label=comp, color=colors[i % len(colors)])
        if present:
            axes[1].set_ylabel("Loss component")
            axes[1].set_xlabel("Step")
            axes[1].set_title("Loss Components")
            axes[1].legend(ncol=3, fontsize=8)

        plt.tight_layout()
        png_path = output_dir / "loss_curves.png"
        plt.savefig(png_path, dpi=150, bbox_inches="tight")
        plt.close()
        log.info(f"Loss curve saved: {png_path}")
        return png_path
    except Exception as exc:
        log.warning(f"Loss curve generation failed: {exc}")
        return None


def _check_monotone(results: dict) -> tuple[bool, str]:
    from peach_loop.phase1.evaluate import check_monotonic_reconstruction
    return check_monotonic_reconstruction(results)
