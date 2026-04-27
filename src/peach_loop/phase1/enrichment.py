"""Gene set and pathway enrichment for Phase 1.

Calls PEACH's published enrichment API:
  pc.tl.gene_associations  — per-archetype differential gene test
  pc.tl.pathway_associations — MSigDB pathway enrichment
  pc.tl.archetype_exclusive_patterns — genes exclusive to one archetype
  pc.tl.tradeoff_patterns    — genes showing trade-offs across archetype pairs

AGENTS.md §3.1 requires per-archetype enrichment.  §3.5 soft criterion: at least
3 significant associations (FDR < 0.05) per top archetype.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from peach_loop.ops.logger import get_logger

log = get_logger("phase1.enrichment")


def run_enrichment(adata: Any, config: Any) -> dict:
    """Run full PEACH enrichment pipeline.

    Returns a dict with keys:
      gene_assoc, pathway_assoc, exclusive_patterns, tradeoff_patterns,
      soft_criterion_check
    """
    import peach as pc

    enr_cfg = getattr(config, "enrichment", config)
    gene_cfg = getattr(enr_cfg, "gene_associations", enr_cfg)
    path_cfg = getattr(enr_cfg, "pathway_associations", enr_cfg)

    fdr_scope = getattr(gene_cfg, "fdr_scope", "global")
    min_logfc = float(getattr(gene_cfg, "min_logfc", 0.1))
    path_fdr_scope = getattr(path_cfg, "fdr_scope", "global")

    log.info("Running gene associations …")
    try:
        pc.tl.gene_associations(adata, fdr_scope=fdr_scope, min_logfc=min_logfc)
        gene_assoc_ok = True
    except Exception as exc:
        log.warning(f"gene_associations failed: {exc}")
        gene_assoc_ok = False

    log.info("Running pathway associations …")
    try:
        pc.tl.pathway_associations(adata, fdr_scope=path_fdr_scope)
        pathway_assoc_ok = True
    except Exception as exc:
        log.warning(f"pathway_associations failed: {exc}")
        pathway_assoc_ok = False

    log.info("Running exclusive patterns …")
    try:
        pc.tl.archetype_exclusive_patterns(adata, min_effect_size=0.05)
        exclusive_ok = True
    except Exception as exc:
        log.warning(f"archetype_exclusive_patterns failed: {exc}")
        exclusive_ok = False

    log.info("Running trade-off patterns …")
    try:
        pc.tl.tradeoff_patterns(adata, tradeoffs="pairs", min_effect_size=0.1)
        tradeoff_ok = True
    except Exception as exc:
        log.warning(f"tradeoff_patterns failed: {exc}")
        tradeoff_ok = False

    # Soft criterion check: ≥ 3 sig associations per top archetype
    acceptance_cfg = getattr(config, "acceptance", None)
    fdr_thresh = float(getattr(acceptance_cfg, "gene_set_fdr_threshold", 0.05)) if acceptance_cfg else 0.05
    min_assoc = int(getattr(acceptance_cfg, "gene_set_per_archetype_min", 3)) if acceptance_cfg else 3
    soft_check = check_soft_criterion(adata, fdr_thresh, min_assoc) if gene_assoc_ok else {}

    # Update immune marker check now that gene associations are available
    acceptance = getattr(config, "acceptance", None)
    known_markers = (
        {k: list(v) for k, v in getattr(acceptance, "known_markers", {}).items()}
        if acceptance else {}
    )
    marker_check = annotate_marker_archetypes(adata, known_markers) if gene_assoc_ok else {}

    return {
        "gene_assoc_ok": gene_assoc_ok,
        "pathway_assoc_ok": pathway_assoc_ok,
        "exclusive_ok": exclusive_ok,
        "tradeoff_ok": tradeoff_ok,
        "soft_criterion": soft_check,
        "marker_check": marker_check,
    }


def check_soft_criterion(
    adata: Any,
    fdr_threshold: float = 0.05,
    min_per_archetype: int = 3,
) -> dict:
    """Check soft criterion: ≥ min_per_archetype significant gene set associations per archetype.

    Returns {archetype_idx: {"n_sig": int, "passes": bool}}.
    """
    result = {}
    # PEACH stores gene association results in adata.uns under a key like 'peach_gene_assoc'
    # The exact key depends on PEACH's internal convention; try common options.
    gene_assoc = (
        adata.uns.get("peach_gene_assoc")
        or adata.uns.get("gene_associations")
        or adata.uns.get("peach", {}).get("gene_associations")
    )
    if gene_assoc is None:
        log.warning("Gene association results not found in adata.uns — skipping soft criterion check")
        return {}

    import pandas as pd

    for arch_key, assoc_df in (gene_assoc.items() if isinstance(gene_assoc, dict) else []):
        if isinstance(assoc_df, pd.DataFrame) and "fdr" in assoc_df.columns:
            n_sig = int((assoc_df["fdr"] < fdr_threshold).sum())
        else:
            n_sig = 0
        result[arch_key] = {"n_sig": n_sig, "passes": n_sig >= min_per_archetype}

    return result


def annotate_marker_archetypes(adata: Any, known_markers: dict[str, list[str]]) -> dict:
    """For each cell type, identify which archetype's top genes best match its markers."""
    if not known_markers:
        return {}

    result = {}
    for cell_type, markers in known_markers.items():
        best_arch = None
        best_overlap = 0

        gene_assoc = (
            adata.uns.get("peach_gene_assoc")
            or adata.uns.get("gene_associations")
            or adata.uns.get("peach", {}).get("gene_associations")
        )
        if gene_assoc and isinstance(gene_assoc, dict):
            import pandas as pd
            for arch_key, assoc_df in gene_assoc.items():
                if isinstance(assoc_df, pd.DataFrame) and "gene" in assoc_df.columns:
                    top_genes = set(assoc_df.nsmallest(50, "fdr")["gene"].tolist() if "fdr" in assoc_df.columns else assoc_df["gene"].head(50).tolist())
                else:
                    top_genes = set()
                overlap = len(set(markers) & top_genes)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_arch = arch_key

        result[cell_type] = {
            "markers": markers,
            "best_archetype": best_arch,
            "overlap_count": best_overlap,
        }

    return result
