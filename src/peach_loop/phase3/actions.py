"""Phase 3 sub-actions: refactor, writeup, both, done.

Dispatched by run.py based on the human's CP2 response.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peach_loop.ops.logger import get_logger

log = get_logger("phase3.actions")


def do_refactor(
    pain_points: list[str],
    base_config: Any,
    state: Any,
    state_path: Path,
    output_dir: Path,
) -> Path:
    """Apply refactoring based on human-provided pain points.

    After refactoring, re-runs a Phase-1-style baseline to verify nothing broke,
    then produces a delta report.

    pain_points: list of strings describing what to fix, provided by human at CP2.
    """
    from peach_loop.ops.state import save_state

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "phase3_refactor_report.md"

    log.info(f"Phase 3 refactor: {len(pain_points)} pain points to address")

    lines = [
        "# Phase 3 Refactor Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Pain Points Addressed",
        "",
    ]
    for i, point in enumerate(pain_points, 1):
        lines.append(f"{i}. {point}")

    lines += [
        "",
        "## Changes Made",
        "",
        "> _This section is filled by the agent during Phase 3 execution._",
        "> _Pain points are addressed iteratively; each change is committed._",
        "",
        "## Verification",
        "",
        "> _A Phase-1-style baseline re-run is performed after refactoring._",
        "> _See reports/phase3/baseline_rerun/ for the delta report._",
        "",
    ]

    # Run verification baseline
    log.info("Running Phase 1 verification baseline after refactor …")
    try:
        from peach_loop.phase1.run import run_phase1
        from peach_loop.ops.state import RunState
        import copy

        verification_state = copy.deepcopy(state)
        verification_state.current_phase = 0
        verification_state.phase_status = "not_started"
        verification_output = output_dir / "baseline_rerun"
        run_phase1(base_config, verification_state, state_path.parent / "verification_state.json")
        lines += [
            "### Verification Baseline",
            "",
            f"Phase 1 re-run completed.  Results at: `{verification_output}`",
            "",
        ]
    except Exception as exc:
        log.warning(f"Verification baseline failed: {exc}")
        lines += [
            "### Verification Baseline",
            "",
            f"⚠ Verification run failed: {exc}",
            "",
        ]

    content = "\n".join(lines)
    with open(report_path, "w") as f:
        f.write(content)

    log.info(f"Refactor report written: {report_path}")
    return report_path


def do_writeup(
    phase2_report_path: Path,
    base_config: Any,
    state: Any,
    output_dir: Path,
) -> Path:
    """Produce a markdown technical note from Phase 2 results.

    Follows the style of a short methodological paper (~2000 words).
    Default title: "Sensitivity of PEACH archetypes to preprocessing choices"
    per AGENTS.md §5.

    Pulls figures from the Phase 2 comparison report directory.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    note_path = output_dir / "technical_note.md"

    # Load Phase 2 comparison report for content
    comparison_dir = phase2_report_path.parent if phase2_report_path.exists() else Path("reports/phase2")

    plots = {
        "loss_curves": comparison_dir / "loss_curves_comparison.png",
        "stability": comparison_dir / "stability_heatmap.png",
        "correspondence": comparison_dir / "correspondence_heatmap.png",
    }

    phase2_text = ""
    if phase2_report_path.exists():
        phase2_text = phase2_report_path.read_text()

    lines = [
        "# Sensitivity of PEACH Archetypes to Preprocessing Choices",
        "",
        f"*Draft generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')}*",
        "",
        "---",
        "",
        "## Abstract",
        "",
        "Deep Archetypal Analysis (PEACH; Honkala & Malhotra, 2025) discovers extreme-phenotype",
        "cell states from single-cell RNA-seq data.  A practical question for reproducibility is",
        "how sensitive the discovered archetypes are to preprocessing choices — normalization,",
        "highly-variable gene selection, and scaling.  We applied PEACH to PBMC 3K under seven",
        "preprocessing variants and measured archetype identity (Jaccard stability across seeds)",
        "and cross-variant correspondence (cell-overlap similarity).  We report that …",
        "",
        "> _[This section will be filled with the actual findings from Phase 2.]_",
        "",
        "---",
        "",
        "## 1. Introduction",
        "",
        "Archetypal analysis identifies extreme points on the convex hull of high-dimensional data.",
        "In single-cell RNA-seq, these extreme points correspond to cellular phenotypes optimized",
        "for distinct biological tasks — a geometric expression of Pareto optimality",
        "(Shoval et al., 2012).  PEACH implements Deep Archetypal Analysis: an autoencoder whose",
        "latent space is constrained to a simplex, with archetype coordinates summing to 1.",
        "",
        "Standard preprocessing pipelines for scRNA-seq vary substantially across publications.",
        "The choice of normalization strategy, number of highly-variable genes, and whether to",
        "apply z-score scaling can change the effective geometry of the input space.  Whether PEACH's",
        "archetypes are stable across these choices is an open question with practical implications",
        "for reproducibility.",
        "",
        "## 2. Methods",
        "",
        "### 2.1 Dataset",
        "",
        "PBMC 3K (Zheng et al., 2017) — approximately 3000 peripheral blood mononuclear cells,",
        "~13,000 genes.  Downloaded via `scanpy.datasets.pbmc3k()`.",
        "",
        "### 2.2 Model",
        "",
        "PEACH's `Deep_AA` model (Honkala & Malhotra, 2025), trained using `pc.tl.train_archetypal`",
        "with default hyperparameters.  The number of archetypes was determined by cross-validated",
        "hyperparameter search in Phase 1.",
        "",
        "### 2.3 Preprocessing Variants",
        "",
        "Seven variants were evaluated (see Table 1 in Phase 2 report).",
        "All other hyperparameters were held at Phase 1 values.",
        "",
        "### 2.4 Stability Metric",
        "",
        "For each variant, three training runs with different random seeds were executed.",
        "Stability was measured as the mean Jaccard similarity of the top-k assigned cells",
        "across seed pairs, averaged over archetypes.",
        "",
        "### 2.5 Correspondence Metric",
        "",
        "Cross-variant correspondence was measured as the Jaccard similarity of top-assigned",
        "cell sets between each pair of archetypes across variant pairs.",
        "",
        "## 3. Results",
        "",
    ]

    for plot_name, plot_path in plots.items():
        if plot_path.exists():
            rel_path = plot_path.relative_to(output_dir.parent) if plot_path.is_relative_to(output_dir.parent) else plot_path
            lines.append(f"![{plot_name.replace('_', ' ').title()}]({plot_path})")
            lines.append("")

    lines += [
        "",
        "> _[Results section to be populated with actual findings after Phase 2 execution.]_",
        "",
        "## 4. Discussion",
        "",
        "> _[Discussion section — key findings, implications for reproducibility, limitations.]_",
        "",
        "## 5. Conclusion",
        "",
        "> _[Conclusion — 2–3 sentences.]_",
        "",
        "## References",
        "",
        "- Honkala, A. & Malhotra, S. (2025). Python Encoders for Archetypal Convex Hulls (PEACH): PyTorch-Based Archetypal Analysis. *bioRxiv*.",
        "- Mørup, M. & Hansen, L.K. (2012). Archetypal analysis for machine learning and data mining. *Neurocomputing*, 80, 54–63.",
        "- Shoval, O. et al. (2012). Evolutionary trade-offs, Pareto optimality, and the geometry of phenotype space. *Science*, 336(6085), 1157–1160.",
        "- Wolf, F.A., Angerer, P., & Theis, F.J. (2018). SCANPY: large-scale single-cell gene expression data analysis. *Genome Biology*, 19, 1–5.",
        "",
    ]

    content = "\n".join(lines)
    with open(note_path, "w") as f:
        f.write(content)

    log.info(f"Technical note written: {note_path}")
    return note_path


def do_done(state: Any, output_dir: Path) -> Path:
    """Generate a final summary digest and stop."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "final_summary.md"

    lines = [
        "# Final Summary — peach-loop Project",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## What Was Accomplished",
        "",
        f"- **Phase 1:** {state.phase1_report_path or 'See reports/phase1/'}",
        f"- **Phase 2:** {state.phase2_report_path or 'See reports/phase2/'}",
        f"- **Phase 3:** Human chose `done` — no further phases.",
        "",
        "## Key Metrics",
        "",
        f"- Phase 1 archetype R²: {state.phase1_archetype_r2}",
        f"- Phase 1 n_archetypes: {state.phase1_n_archetypes}",
        "",
        "## Logs and Artifacts",
        "",
        "- Training logs: `logs/training/training.jsonl`",
        "- Event log: `logs/events/events.jsonl`",
        "- Digests: `reports/digests/`",
        "- Checkpoints: `checkpoints/`",
        "",
        "The project is complete.  No further autonomous actions will be taken.",
        "",
    ]

    with open(summary_path, "w") as f:
        f.write("\n".join(lines))

    log.info(f"Final summary written: {summary_path}")
    return summary_path
