"""Smoke tests for the daily digest generator."""

import sys
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from peach_loop.ops.state import RunState, record_tier2_event
from peach_loop.ops.digest import (
    generate_digest,
    is_digest_due,
    REQUIRED_FIELDS,
    _render_digest,
    _build_context,
)
from peach_loop.config import load_config


def _make_config():
    return load_config(
        str(Path(__file__).parent.parent / "configs" / "base.yaml"),
        str(Path(__file__).parent.parent / "configs" / "phase1.yaml"),
    )


def test_digest_generates_file():
    """Digest file is written and is non-empty."""
    cfg = _make_config()
    state = RunState(current_phase=1, phase_status="running")

    with tempfile.TemporaryDirectory() as tmpdir:
        digest_path = generate_digest(state, cfg, Path(tmpdir))
        assert digest_path.exists(), "Digest file not created"
        content = digest_path.read_text()
        assert len(content) > 100, "Digest content suspiciously short"


def test_digest_contains_required_sections():
    """Digest contains all required fields listed in AGENTS.md §6."""
    cfg = _make_config()
    state = RunState(current_phase=1, phase_status="running")

    with tempfile.TemporaryDirectory() as tmpdir:
        digest_path = generate_digest(state, cfg, Path(tmpdir))
        content = digest_path.read_text()

    # Check headings / field names that AGENTS.md §6 mandates
    required_snippets = [
        "Phase",
        "Budget",          # budget consumed
        "Wall-clock",      # wall-clock since launch
        "ETA",             # eta to next checkpoint
        "Last 24",         # last 24h summary
        "Tier-2",          # tier-2 events
        "Tier-1",          # tier-1 events
        "Pending",         # pending decisions
        "Forecast",        # forecast
        "Plot",            # path to recent plot
    ]
    for snippet in required_snippets:
        assert snippet in content, f"Digest missing required section/field: '{snippet}'"


def test_digest_records_last_date(tmp_path):
    """After generating, state.last_digest_date is set to today."""
    cfg = _make_config()
    state = RunState(current_phase=1, phase_status="running")
    assert state.last_digest_date is None

    generate_digest(state, cfg, tmp_path)
    assert state.last_digest_date == datetime.now().date().isoformat()


def test_digest_not_due_after_generation(tmp_path):
    """is_digest_due returns False immediately after generating."""
    cfg = _make_config()
    state = RunState(current_phase=1, phase_status="running")
    state.last_digest_date = datetime.now().date().isoformat()

    # Should not be due since we just "generated" it
    assert not is_digest_due(state, schedule_hour=0)  # hour=0 so it's always "past schedule"


def test_digest_includes_tier2_events(tmp_path):
    """Tier-2 events from the last 24h appear in the digest."""
    from datetime import timezone
    cfg = _make_config()
    state = RunState(current_phase=1, phase_status="running")
    record_tier2_event(state, protocol="process_crash_resume", message="Test crash recovery")

    digest_path = generate_digest(state, cfg, tmp_path)
    content = digest_path.read_text()
    assert "process_crash_resume" in content or "Test crash recovery" in content


def test_digest_filename_format(tmp_path):
    """Digest filename matches expected pattern: digest_YYYY-MM-DD_HH-MM.md"""
    import re
    cfg = _make_config()
    state = RunState(current_phase=1, phase_status="running")
    digest_path = generate_digest(state, cfg, tmp_path)
    assert re.match(r"digest_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.md", digest_path.name), (
        f"Unexpected digest filename format: {digest_path.name}"
    )
