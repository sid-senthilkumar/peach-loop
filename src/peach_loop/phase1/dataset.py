"""Dataset acquisition and preprocessing for Phase 1.

Downloads PBMC 3K via scanpy (with 10x fallback), verifies SHA-256,
then runs the standard scanpy preprocessing pipeline described in AGENTS.md §3.3.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peach_loop.ops.logger import get_logger

log = get_logger("phase1.dataset")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_pbmc3k(config: Any, raw_dir: Path) -> Any:
    """Download PBMC 3K, verify hash, return raw AnnData.

    Source priority:
    1. scanpy.datasets.pbmc3k() — ships with scanpy, downloads to scanpy cache.
    2. Direct 10x URL — fallback if scanpy source fails.

    The SHA-256 of the downloaded h5ad is written to raw_dir/pbmc3k_sha256.txt
    on first download and verified on subsequent runs.
    """
    import scanpy as sc

    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_dir / "pbmc3k_raw.h5ad"
    hash_path = raw_dir / "pbmc3k_sha256.txt"
    meta_path = raw_dir / "pbmc3k_download_meta.json"

    if cache_path.exists():
        log.info(f"Cached dataset found: {cache_path}")
        _verify_stored_hash(cache_path, hash_path)
        import anndata
        return anndata.read_h5ad(cache_path)

    # Primary source: scanpy
    log.info("Downloading PBMC 3K via scanpy.datasets.pbmc3k() …")
    adata = _download_via_scanpy(config)

    # Save to our own cache path
    log.info(f"Saving to cache: {cache_path}")
    adata.write_h5ad(cache_path)

    # Record hash and metadata
    sha256 = _compute_sha256(cache_path)
    hash_path.write_text(sha256 + "\n")
    log.info(f"SHA-256 recorded: {sha256}")

    meta = {
        "source": "scanpy.datasets.pbmc3k",
        "download_ts": datetime.now(timezone.utc).isoformat(),
        "n_cells": adata.n_obs,
        "n_genes": adata.n_vars,
        "sha256": sha256,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return adata


def _download_via_scanpy(config: Any) -> Any:
    """Download via scanpy, with one retry via the 10x fallback URL."""
    import scanpy as sc

    try:
        adata = sc.datasets.pbmc3k()
        log.info(f"scanpy download succeeded: {adata.n_obs} cells × {adata.n_vars} genes")
        return adata
    except Exception as exc:
        log.warning(f"scanpy download failed ({exc}); trying fallback URL …")

    fallback_url = getattr(getattr(config, "dataset", config), "fallback_url", None)
    if fallback_url is None:
        raise RuntimeError("scanpy download failed and no fallback URL configured")

    return _download_via_url(fallback_url)


def _download_via_url(url: str) -> Any:
    """Download 10x tar.gz from URL, extract, load as AnnData."""
    import urllib.request
    import tarfile
    import tempfile
    import scanpy as sc

    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = Path(tmpdir) / "pbmc3k.tar.gz"
        log.info(f"Downloading from {url} …")
        urllib.request.urlretrieve(url, tar_path)
        with tarfile.open(tar_path) as tar:
            tar.extractall(tmpdir)
        # 10x format: find filtered_gene_bc_matrices/
        matrix_dirs = list(Path(tmpdir).rglob("filtered_gene_bc_matrices"))
        if not matrix_dirs:
            raise RuntimeError("Expected filtered_gene_bc_matrices/ not found in archive")
        adata = sc.read_10x_mtx(matrix_dirs[0] / "hg19", var_names="gene_symbols", cache=False)
        adata.var_names_make_unique()
    return adata


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_stored_hash(data_path: Path, hash_path: Path) -> None:
    if not hash_path.exists():
        log.warning("No stored hash found — skipping hash verification for cached file")
        return
    stored = hash_path.read_text().strip()
    actual = _compute_sha256(data_path)
    if actual != stored:
        raise RuntimeError(
            f"Hash mismatch for {data_path}:\n  stored:  {stored}\n  actual:  {actual}\n"
            "Data corruption detected (Tier-1 condition per AGENTS.md §8)."
        )
    log.info("SHA-256 verified OK")


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def preprocess_adata(adata: Any, config: Any) -> Any:
    """Apply the standard scanpy PBMC tutorial preprocessing pipeline.

    This is the Phase 1 reference pipeline (AGENTS.md §3.3).
    Returns a new AnnData with the processed data stored in .X and PCA in .obsm.
    """
    import scanpy as sc
    import numpy as np

    pp = getattr(config, "preprocessing", config)
    log.info(f"Preprocessing: {adata.n_obs} cells × {adata.n_vars} genes")

    # Work on a copy so raw data is preserved
    adata = adata.copy()
    adata.var_names_make_unique()

    # Basic quality filtering
    sc.pp.filter_cells(adata, min_genes=int(getattr(pp, "filter_cells_min_genes", 200)))
    sc.pp.filter_genes(adata, min_cells=int(getattr(pp, "filter_genes_min_cells", 3)))
    log.info(f"After filtering: {adata.n_obs} cells × {adata.n_vars} genes")

    # Normalise
    target = getattr(pp, "normalize_total_target", None)
    if target is not None:
        sc.pp.normalize_total(adata, target_sum=float(target))

    # Log transform
    if getattr(pp, "log_transform", True):
        sc.pp.log1p(adata)

    # Highly variable genes
    n_hvg = getattr(pp, "n_highly_variable_genes", None)
    hvg_flavor = getattr(pp, "hvg_flavor", "seurat")
    if n_hvg is not None:
        sc.pp.highly_variable_genes(adata, n_top_genes=int(n_hvg), flavor=hvg_flavor)
        adata = adata[:, adata.var.highly_variable].copy()
        log.info(f"After HVG selection ({n_hvg}): {adata.n_obs} cells × {adata.n_vars} genes")

    # Scale
    if getattr(pp, "scale", True):
        sc.pp.scale(adata, max_value=10)

    # PCA
    n_pcs = int(getattr(pp, "pca_components", 50))
    n_pcs = min(n_pcs, min(adata.n_obs, adata.n_vars) - 1)
    sc.tl.pca(adata, n_comps=n_pcs, svd_solver="arpack")
    log.info(f"PCA: {n_pcs} components computed")

    return adata


def train_test_split_adata(adata: Any, train_frac: float = 0.8, seed: int = 42) -> tuple[Any, Any]:
    """Split AnnData into train and test sets (by cell index)."""
    import numpy as np

    rng = np.random.default_rng(seed)
    n = adata.n_obs
    idx = rng.permutation(n)
    n_train = int(n * train_frac)
    train_idx = idx[:n_train]
    test_idx = idx[n_train:]
    return adata[train_idx].copy(), adata[test_idx].copy()
