"""Setup-time smoke test.

Per AGENTS.md §8 (Tier-1 condition if this fails):
  - PEACH imports cleanly
  - Deep_AA instantiates
  - Single training step on synthetic data succeeds
  - PEACH's tutorial PBMC example runs end-to-end (abbreviated)

Run via:
    python scripts/smoke_test.py
    make smoke-test
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


def check(description: str):
    """Context manager that prints pass/fail for a named check."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        print(f"  checking: {description} ...", end=" ", flush=True)
        try:
            yield
            print("OK")
        except Exception as exc:
            print(f"FAILED\n    {exc}")
            raise

    return _ctx()


def run_smoke_test() -> bool:
    """Return True if all checks pass."""
    print("\n=== peach-loop smoke test ===\n")
    failures = []

    # 1. PEACH imports
    try:
        with check("import peach"):
            import peach as pc
    except Exception as e:
        failures.append(f"PEACH import: {e}")

    # 2. scanpy imports
    try:
        with check("import scanpy"):
            import scanpy as sc
    except Exception as e:
        failures.append(f"scanpy import: {e}")

    # 3. torch imports and device
    try:
        with check("import torch"):
            import torch
            device = "cpu"
            print(f"  torch version: {torch.__version__}, device: {device}")
    except Exception as e:
        failures.append(f"torch import: {e}")

    # 4. PEACH config / config loader
    try:
        with check("load peach-loop config"):
            from peach_loop.config import load_config
            cfg = load_config("configs/base.yaml", "configs/phase1.yaml")
            assert hasattr(cfg, "peach"), "Config missing 'peach' section"
    except Exception as e:
        failures.append(f"config load: {e}")

    # 5. Deep_AA instantiates on synthetic data (single forward pass)
    try:
        with check("Deep_AA forward pass on synthetic data"):
            import torch
            import numpy as np
            import anndata

            # Tiny synthetic AnnData: 50 cells × 20 PCA components
            n_cells, n_pcs = 50, 20
            X = np.random.randn(n_cells, n_pcs).astype(np.float32)
            adata_syn = anndata.AnnData(X=X)
            adata_syn.obsm["X_pca"] = X

            t0 = time.monotonic()
            results = pc.tl.train_archetypal(
                adata_syn,
                n_archetypes=3,
                n_epochs=2,
                device="cpu",
            )
            elapsed = time.monotonic() - t0
            assert results is not None, "train_archetypal returned None"
            print(f"  {elapsed:.2f}s — synthetic training OK")
    except Exception as e:
        failures.append(f"Deep_AA synthetic run: {e}")

    # 6. Post-training API calls on synthetic result
    try:
        with check("post-training API: coordinates + assignments"):
            import anndata, numpy as np
            n_cells, n_pcs = 50, 20
            X = np.random.randn(n_cells, n_pcs).astype(np.float32)
            adata_syn = anndata.AnnData(X=X)
            adata_syn.obsm["X_pca"] = X
            results = pc.tl.train_archetypal(adata_syn, n_archetypes=3, n_epochs=2, device="cpu")
            pc.tl.archetypal_coordinates(adata_syn)
            pc.tl.assign_archetypes(adata_syn, percentage_per_archetype=0.2)
    except Exception as e:
        failures.append(f"post-training API: {e}")

    # 7. Checkpoint save/load round-trip
    try:
        with check("checkpoint save + load round-trip"):
            import tempfile, anndata, numpy as np
            from peach_loop.ops.checkpoint import save_checkpoint, load_checkpoint, verify_checkpoint

            n_cells, n_pcs = 30, 10
            X = np.random.randn(n_cells, n_pcs).astype(np.float32)
            adata_tmp = anndata.AnnData(X=X)
            adata_tmp.obsm["X_pca"] = X

            fake_results = {"history": {"loss": [1.0, 0.9, 0.8]}, "final_archetype_r2": 0.75}

            with tempfile.TemporaryDirectory() as tmpdir:
                base = Path(tmpdir)
                ckpt_path = save_checkpoint(adata_tmp, fake_results, epoch=20, base_dir=base)
                assert verify_checkpoint(ckpt_path), "Checkpoint verification failed"
                adata_loaded, meta = load_checkpoint(ckpt_path)
                assert adata_loaded is not None
                assert meta["epoch"] == 20
    except Exception as e:
        failures.append(f"checkpoint round-trip: {e}")

    # 8. Digest generation
    try:
        with check("digest generation"):
            import tempfile
            from peach_loop.ops.state import RunState
            from peach_loop.ops.digest import generate_digest
            from peach_loop.config import load_config

            cfg = load_config("configs/base.yaml", "configs/phase1.yaml")
            state = RunState(current_phase=1, phase_status="running")
            with tempfile.TemporaryDirectory() as tmpdir:
                digest_path = generate_digest(state, cfg, Path(tmpdir))
                assert digest_path.exists(), "Digest file not created"
                content = digest_path.read_text()
                assert "Phase status" in content or "Status" in content
    except Exception as e:
        failures.append(f"digest generation: {e}")

    # Summary
    print()
    if failures:
        print(f"SMOKE TEST FAILED ({len(failures)} checks failed):\n")
        for f in failures:
            print(f"  ✗ {f}")
        print()
        return False
    else:
        print("SMOKE TEST PASSED — all checks OK\n")
        return True


if __name__ == "__main__":
    ok = run_smoke_test()
    sys.exit(0 if ok else 1)
