"""Unit test: resume-from-checkpoint (AGENTS.md §3.5).

This is a self-contained pytest wrapper around scripts/resume_test.py.
Running `make test` includes this automatically.
Running `make test-resume` runs the standalone script directly.
"""

import sys
from pathlib import Path

# Ensure src/ is on path for all tests
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_resume_from_checkpoint():
    """Resume test: final loss after mid-point interrupt must match reference within tolerance."""
    # Import here so the test is skipped gracefully if PEACH isn't installed
    pytest = __import__("pytest")
    try:
        import peach  # noqa: F401
    except ImportError:
        pytest.skip("PEACH not installed — skipping resume test")

    # Run the resume test script logic directly
    import importlib.util, types

    spec = importlib.util.spec_from_file_location(
        "resume_test",
        Path(__file__).parent.parent / "scripts" / "resume_test.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    passed = module.run_resume_test()
    assert passed, (
        "Resume test failed: final loss after checkpoint resume diverges from reference "
        "beyond the allowed tolerance. See scripts/resume_test.py for details."
    )
