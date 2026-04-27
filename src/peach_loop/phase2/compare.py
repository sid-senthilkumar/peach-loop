"""Comparison report generation for Phase 2 sweep.

Produces a markdown report plus three plots as required by AGENTS.md §4.2:
  1. Loss curves overlaid
  2. Stability heatmap (Jaccard across seeds)
  3. Archetype correspondence heatmap (across variants)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peach_loop.ops.logger import get_logger

log = get_logger("phase2.compare")


def generate_comparison_report(
    all_results: dict[str, list[dict]],
    stability_scores: dict[str, float],
    correspondence_matrices: dict[tuple[str, str], list[list[float]]],
    config: Any,
    output_dir: Path,
) -> Path:
    """Write comparison report to output_dir/phase2_comparison.md.

    all_results: {variant_name: [result_dict_seed1, result_dict_seed2, ...]}
    stability_scores: {variant_name: jaccard_score}
    correspondence_matrices: {(variant_a, variant_b): matrix}
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "phase2_comparison.md"

    cmp_cfg = getattr(config, "comparison", None)
    top_n = int(getattr(cmp_cfg, "top_archetypes_for_enrichment", 3)) if cmp_cfg else 3

    # Generate plots
    loss_plot = _plot_loss_curves(all_results, output_dir)
    stability_plot = _plot_stability_heatmap(stability_scores, output_dir)
    corr_plot = _plot_correspondence_heatmap(correspondence_matrices, output_dir)

    # Build report
    lines = [
        "# Phase 2 Comparison Report — Preprocessing Sweep",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "---",
        "",
        "## 1. Per-Variant Summary",
        "",
        "| Variant | Final Loss | R² | Stability (Jaccard) | Status |",
        "|---------|-----------|-----|---------------------|--------|",
    ]

    variant_names = list(all_results.keys())
    for name in variant_names:
        results = all_results[name]
        completed = [r for r in results if r.get("status") == "complete"]
        if completed:
            avg_loss = sum(r["final_loss"] for r in completed if r["final_loss"] is not None) / max(1, len(completed))
            avg_r2 = sum(r["final_archetype_r2"] for r in completed if r["final_archetype_r2"] is not None) / max(1, len(completed))
            losses_str = f"{avg_loss:.4f}"
            r2_str = f"{avg_r2:.4f}"
        else:
            losses_str = "FAILED"
            r2_str = "FAILED"

        stab = stability_scores.get(name, float("nan"))
        stab_str = f"{stab:.3f}" if stab == stab else "N/A"  # nan check
        n_failed = len([r for r in results if r.get("status") != "complete"])
        status = "✓" if not n_failed else f"⚠ {n_failed} failed"
        lines.append(f"| {name} | {losses_str} | {r2_str} | {stab_str} | {status} |")

    lines += [
        "",
        "## 2. Loss Trajectories",
        "",
        "> Mean trajectory across seeds per variant.",
        "",
    ]
    if loss_plot:
        lines.append(f"![Loss curves overlaid]({loss_plot.name})")
    else:
        lines.append("_Plot not generated._")

    lines += [
        "",
        "## 3. Archetype Stability",
        "",
        "> Jaccard similarity of top-k archetype-assigned cells across 3 seeds.",
        "> Higher = more stable archetypes across random initializations.",
        "",
    ]
    if stability_plot:
        lines.append(f"![Stability heatmap]({stability_plot.name})")
    lines.append("")
    for name in variant_names:
        stab = stability_scores.get(name, float("nan"))
        stab_str = f"{stab:.3f}" if stab == stab else "N/A"
        lines.append(f"- **{name}:** {stab_str}")

    lines += [
        "",
        "## 4. Archetype Correspondence Across Variants",
        "",
        "> Pairwise correspondence: which archetypes in variant A map to which in variant B.",
        "> Based on cell overlap (Jaccard) of top-assigned cells.",
        "",
    ]
    if corr_plot:
        lines.append(f"![Correspondence heatmap]({corr_plot.name})")
    lines.append("")

    lines += [
        "",
        "## 5. Top Gene-Set Enrichment per Variant (top 3 archetypes)",
        "",
    ]
    for name in variant_names:
        results = all_results[name]
        completed = [r for r in results if r.get("status") == "complete"]
        lines.append(f"### {name}")
        if not completed:
            lines.append("_All seeds failed._\n")
            continue
        enr = completed[0].get("enrichment_top3", {})
        if enr:
            for arch_key, genes in list(enr.items())[:top_n]:
                genes_str = ", ".join(str(g) for g in (genes or [])[:10])
                lines.append(f"- **Archetype {arch_key}:** {genes_str}")
        else:
            lines.append("_Enrichment not available._")
        lines.append("")

    lines += [
        "",
        "## 6. Acceptance Criteria (AGENTS.md §4.4)",
        "",
        "| Criterion | Status |",
        "|-----------|--------|",
        f"| All variants attempted | {'✓' if len(all_results) >= 6 else '⚠'} ({len(all_results)} variants) |",
        "| Comparison report exists | ✓ |",
        "| Daily digest continued | See reports/digests/ |",
        "",
        "---",
        "",
        "## 7. Observations",
        "",
        "_To be filled by the human at CP2 review._",
        "",
        "Key question from AGENTS.md: Does archetype identity survive preprocessing changes?",
        "See the correspondence heatmap (Section 4) and stability scores (Section 3) for evidence.",
        "",
    ]

    content = "\n".join(lines)
    with open(report_path, "w") as f:
        f.write(content)

    log.info(f"Comparison report written: {report_path}")
    return report_path


# ── Plot helpers ─────────────────────────────────────────────────────────────

def _plot_loss_curves(all_results: dict, output_dir: Path) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        fig, ax = plt.subplots(figsize=(12, 5))
        colors = plt.cm.tab10.colors

        for i, (name, results) in enumerate(all_results.items()):
            completed = [r for r in results if r.get("loss_history")]
            if not completed:
                continue
            # Average across seeds (pad to same length)
            max_len = max(len(r["loss_history"]) for r in completed)
            padded = [r["loss_history"] + [r["loss_history"][-1]] * (max_len - len(r["loss_history"])) for r in completed]
            mean_loss = np.mean(padded, axis=0)
            std_loss = np.std(padded, axis=0)
            xs = np.arange(len(mean_loss))
            color = colors[i % len(colors)]
            ax.plot(xs, mean_loss, label=name, color=color, linewidth=1.5)
            ax.fill_between(xs, mean_loss - std_loss, mean_loss + std_loss, alpha=0.15, color=color)

        ax.set_xlabel("Training step")
        ax.set_ylabel("Total loss")
        ax.set_title("Loss trajectories — all preprocessing variants")
        ax.legend(fontsize=8, ncol=2)
        plt.tight_layout()
        p = output_dir / "loss_curves_comparison.png"
        plt.savefig(p, dpi=150, bbox_inches="tight")
        plt.close()
        return p
    except Exception as exc:
        log.warning(f"Loss curve plot failed: {exc}")
        return None


def _plot_stability_heatmap(stability_scores: dict, output_dir: Path) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        names = list(stability_scores.keys())
        scores = [stability_scores[n] for n in names]

        fig, ax = plt.subplots(figsize=(max(6, len(names) * 0.8), 3))
        bars = ax.bar(range(len(names)), scores, color=plt.cm.RdYlGn([s if s == s else 0 for s in scores]))
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=30, ha="right", fontsize=9)
        ax.set_ylabel("Jaccard stability (mean across seeds)")
        ax.set_title("Archetype stability by preprocessing variant")
        ax.set_ylim(0, 1)
        ax.axhline(0.5, color="gray", linestyle="--", linewidth=0.8, label="0.5 reference")
        ax.legend(fontsize=8)
        plt.tight_layout()
        p = output_dir / "stability_heatmap.png"
        plt.savefig(p, dpi=150, bbox_inches="tight")
        plt.close()
        return p
    except Exception as exc:
        log.warning(f"Stability heatmap failed: {exc}")
        return None


def _plot_correspondence_heatmap(
    correspondence_matrices: dict,
    output_dir: Path,
) -> Path | None:
    if not correspondence_matrices:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        pairs = list(correspondence_matrices.keys())
        n_pairs = len(pairs)
        if n_pairs == 0:
            return None

        cols = min(3, n_pairs)
        rows = (n_pairs + cols - 1) // cols
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 4, rows * 3.5), squeeze=False)

        for idx, (pair, matrix) in enumerate(correspondence_matrices.items()):
            row, col = divmod(idx, cols)
            ax = axes[row][col]
            if not matrix:
                ax.axis("off")
                continue
            mat = np.array(matrix)
            im = ax.imshow(mat, vmin=0, vmax=1, cmap="Blues", aspect="auto")
            ax.set_title(f"{pair[0]}\nvs\n{pair[1]}", fontsize=7)
            ax.set_xlabel("Archetypes (variant B)", fontsize=7)
            ax.set_ylabel("Archetypes (variant A)", fontsize=7)
            plt.colorbar(im, ax=ax, fraction=0.04)

        # Hide empty subplots
        for idx in range(n_pairs, rows * cols):
            row, col = divmod(idx, cols)
            axes[row][col].axis("off")

        plt.suptitle("Archetype correspondence across preprocessing variants", fontsize=10)
        plt.tight_layout()
        p = output_dir / "correspondence_heatmap.png"
        plt.savefig(p, dpi=150, bbox_inches="tight")
        plt.close()
        return p
    except Exception as exc:
        log.warning(f"Correspondence heatmap failed: {exc}")
        return None
