"""Resume-from-checkpoint test (AGENTS.md §3.5 acceptance criterion).

Protocol:
  1. Run training for N_total epochs, record the final loss — the "reference" run.
  2. Run training for N_total/2 epochs, save checkpoint, simulate a crash.
  3. Resume from the checkpoint, run remaining N_total/2 epochs.
  4. Verify the final loss of the resumed run is within tolerance of the reference.

This test uses synthetic data (tiny AnnData) so it runs in seconds without
real PBMC data.  The tolerance is intentionally loose (10%) because PEACH's
warm-start from adata.uns may not produce byte-identical results — see
docs/decisions.md for the design note.

Usage:
    python scripts/resume_test.py
    make test-resume
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

TOLERANCE = 0.10   # final loss within 10% of reference
N_TOTAL_EPOCHS = 20
N_CELLS = 80
N_PCS = 15
N_ARCHETYPES = 3


def make_synthetic_adata():
    import numpy as np
    import anndata

    rng = np.random.default_rng(42)
    X = rng.standard_normal((N_CELLS, N_PCS)).astype("float32")
    adata = anndata.AnnData(X=X)
    adata.obsm["X_pca"] = X
    return adata


def run_reference(adata):
    """Run N_total epochs uninterrupted; return final loss."""
    import peach as pc
    import torch, numpy as np
    torch.manual_seed(42)
    np.random.seed(42)

    results = pc.tl.train_archetypal(
        adata.copy(),
        n_archetypes=N_ARCHETYPES,
        n_epochs=N_TOTAL_EPOCHS,
        device="cpu",
    )
    history = results.get("history", {})
    losses = history.get("loss", [])
    return float(losses[-1]) if losses else None, results


def run_with_resume(adata, tmpdir: Path):
    """Run half, checkpoint, resume, finish. Return final loss."""
    import peach as pc
    import torch, numpy as np
    from peach_loop.ops.checkpoint import save_checkpoint, load_checkpoint

    half = N_TOTAL_EPOCHS // 2

    # First half
    torch.manual_seed(42)
    np.random.seed(42)
    adata_mid = adata.copy()
    results_mid = pc.tl.train_archetypal(
        adata_mid,
        n_archetypes=N_ARCHETYPES,
        n_epochs=half,
        device="cpu",
    )

    # Save checkpoint
    ckpt_path = save_checkpoint(adata_mid, results_mid, epoch=half, base_dir=tmpdir / "ckpts")
    print(f"  Checkpoint saved: {ckpt_path}")

    # Simulate crash — reload from checkpoint
    adata_resumed, meta = load_checkpoint(ckpt_path)
    print(f"  Checkpoint loaded: epoch={meta.get('epoch')}")

    # Second half
    torch.manual_seed(42 + half)  # different seed for second half (as in real crash scenario)
    results_final = pc.tl.train_archetypal(
        adata_resumed,
        n_archetypes=N_ARCHETYPES,
        n_epochs=N_TOTAL_EPOCHS - half,
        device="cpu",
    )
    history = results_final.get("history", {})
    losses = history.get("loss", [])
    return float(losses[-1]) if losses else None


def run_resume_test() -> bool:
    print("\n=== Resume-from-checkpoint test ===\n")
    print(f"  N_total_epochs={N_TOTAL_EPOCHS}, N_cells={N_CELLS}, N_pcs={N_PCS}, tolerance={TOLERANCE:.0%}")
    print()

    adata = make_synthetic_adata()

    print("  [1/3] Running reference (uninterrupted) …")
    ref_loss, _ = run_reference(adata)
    if ref_loss is None:
        print("  FAILED: reference run returned no loss history")
        return False
    print(f"  Reference final loss: {ref_loss:.6f}")

    print("  [2/3] Running with mid-point checkpoint + resume …")
    with tempfile.TemporaryDirectory() as tmpdir:
        resumed_loss = run_with_resume(adata, Path(tmpdir))

    if resumed_loss is None:
        print("  FAILED: resumed run returned no loss history")
        return False
    print(f"  Resumed final loss:   {resumed_loss:.6f}")

    # Tolerance check
    if ref_loss == 0:
        passes = resumed_loss < 1e-6
    else:
        relative_diff = abs(resumed_loss - ref_loss) / abs(ref_loss)
        passes = relative_diff <= TOLERANCE
        print(f"  Relative difference:  {relative_diff:.2%}  (threshold: {TOLERANCE:.0%})")

    print()
    if passes:
        print("RESUME TEST PASSED\n")
    else:
        print(f"RESUME TEST FAILED — final losses diverge beyond {TOLERANCE:.0%} tolerance\n")
        print("  See docs/decisions.md §Resume mechanism for design notes.")

    return passes


if __name__ == "__main__":
    ok = run_resume_test()
    sys.exit(0 if ok else 1)
