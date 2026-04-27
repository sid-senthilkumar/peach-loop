"""Preprocessing variant definitions for Phase 2 sweep.

Each variant is a named set of preprocessing parameters.
`apply_variant_preprocessing` applies the variant to a fresh copy of raw AnnData.
"""

from __future__ import annotations

from typing import Any

from peach_loop.ops.logger import get_logger

log = get_logger("phase2.variants")


def apply_variant_preprocessing(adata_raw: Any, variant_cfg: Any) -> Any:
    """Preprocess a raw AnnData according to a variant config.

    variant_cfg is a Config object with a .preprocessing sub-config.
    Returns a new AnnData (copy of adata_raw, processed in place).
    """
    import scanpy as sc

    pp = getattr(variant_cfg, "preprocessing", variant_cfg)
    name = getattr(variant_cfg, "name", "unnamed")
    log.info(f"Variant '{name}': preprocessing {adata_raw.n_obs} cells × {adata_raw.n_vars} genes")

    adata = adata_raw.copy()
    adata.var_names_make_unique()

    # Filtering
    sc.pp.filter_cells(adata, min_genes=int(getattr(pp, "filter_cells_min_genes", 200)))
    sc.pp.filter_genes(adata, min_cells=int(getattr(pp, "filter_genes_min_cells", 3)))

    # Normalisation
    target = getattr(pp, "normalize_total_target", None)
    if target is not None:
        sc.pp.normalize_total(adata, target_sum=float(target))

    # Log transform
    if getattr(pp, "log_transform", False):
        sc.pp.log1p(adata)

    # HVG selection
    n_hvg = getattr(pp, "n_highly_variable_genes", None)
    if n_hvg is not None:
        flavor = getattr(pp, "hvg_flavor", "seurat")
        sc.pp.highly_variable_genes(adata, n_top_genes=int(n_hvg), flavor=flavor)
        adata = adata[:, adata.var.highly_variable].copy()

    # Scaling
    if getattr(pp, "scale", False):
        sc.pp.scale(adata, max_value=10)

    # PCA
    n_pcs = int(getattr(pp, "pca_components", 50))
    n_pcs = min(n_pcs, min(adata.n_obs, adata.n_vars) - 1)
    sc.tl.pca(adata, n_comps=n_pcs, svd_solver="arpack")

    log.info(f"Variant '{name}' after preprocessing: {adata.n_obs} × {adata.n_vars}")
    return adata


def get_variants_from_config(sweep_config: Any) -> list[Any]:
    """Return the list of variant config objects from a sweep config."""
    return list(getattr(sweep_config, "variants", []))
