"""Tests for v0.2 Slice 4 multi-assumption reliability aggregation.

Gate 1 now attaches a list of assumptions when multiple strategies
fire in agreement. Gate 2 still consumes a single (reliability,
sample_size) pair. `aggregateReliability` is the bridge between the
two: it reduces a list of per-assumption stats to the most
conservative pair (min reliability, min sample_size).

These tests exercise the aggregation function through three layers:
the Lean CLI, the Python bridge, and the journal's batch lookup.
"""

from __future__ import annotations

import pytest

from python import journal
from python.bridge import VeritasCore


@pytest.fixture(scope="module")
def core() -> VeritasCore:
    return VeritasCore()


# ── Lean-side aggregation through the CLI bridge ─────────────────

def test_aggregate_empty_returns_default(core):
    out = core.aggregate_reliability([])
    assert out["reliability"] == pytest.approx(0.5)
    assert out["sample_size"] == 0


def test_aggregate_single_passes_through(core):
    out = core.aggregate_reliability([{"wins": 8, "total": 10}])
    assert out["reliability"] == pytest.approx(0.8)
    assert out["sample_size"] == 10


def test_aggregate_two_takes_min_reliability(core):
    """First: 8/10 = 0.8. Second: 2/5 = 0.4. Aggregate: 0.4 (min)."""
    out = core.aggregate_reliability([
        {"wins": 8, "total": 10},
        {"wins": 2, "total": 5},
    ])
    assert out["reliability"] == pytest.approx(0.4)
    assert out["sample_size"] == 5  # min total


def test_aggregate_three_takes_min_across_all(core):
    """(8/10, 2/5, 6/6) → min reliability 0.4, min sample_size 5."""
    out = core.aggregate_reliability([
        {"wins": 8, "total": 10},
        {"wins": 2, "total": 5},
        {"wins": 6, "total": 6},
    ])
    assert out["reliability"] == pytest.approx(0.4)
    assert out["sample_size"] == 5


def test_aggregate_zero_total_not_included_as_divisor_surprise(core):
    """A 0/0 assumption surfaces as 0.5 default; the aggregate should
    still take min(other, 0.5). Here (0/0, 8/10) → min(0.5, 0.8) = 0.5,
    min sample_size = 0."""
    out = core.aggregate_reliability([
        {"wins": 0, "total": 0},
        {"wins": 8, "total": 10},
    ])
    assert out["reliability"] == pytest.approx(0.5)
    assert out["sample_size"] == 0  # min total is 0 — forces exploration


# ── Journal batch-lookup helper ──────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    journal._conn = None
    journal.init_db(p)
    journal.seed_assumptions()
    yield p
    journal._conn = None


def test_journal_seeds_both_assumptions(db_path):
    f = journal.get_assumption_stats("funding_rate_reverts_within_8h")
    b = journal.get_assumption_stats("basis_reverts_within_24h")
    assert f == {"wins": 0, "total": 0}
    assert b == {"wins": 0, "total": 0}


def test_journal_batch_lookup_returns_both(db_path):
    stats = journal.get_assumption_stats_many([
        "funding_rate_reverts_within_8h",
        "basis_reverts_within_24h",
    ])
    assert set(stats.keys()) == {
        "funding_rate_reverts_within_8h",
        "basis_reverts_within_24h",
    }
    for v in stats.values():
        assert v == {"wins": 0, "total": 0}


def test_journal_batch_lookup_defaults_unknown(db_path):
    stats = journal.get_assumption_stats_many(["nonexistent_assumption"])
    assert stats == {"nonexistent_assumption": {"wins": 0, "total": 0}}


def test_journal_updated_stats_flow_through_aggregate(db_path, core):
    """End-to-end: update two assumption rows, read them via batch
    lookup, feed to aggregate_reliability, verify the min behavior."""
    journal.update_assumption_stats(
        "funding_rate_reverts_within_8h", {"wins": 7, "total": 10})
    journal.update_assumption_stats(
        "basis_reverts_within_24h", {"wins": 3, "total": 8})

    stats = journal.get_assumption_stats_many([
        "funding_rate_reverts_within_8h",
        "basis_reverts_within_24h",
    ])
    out = core.aggregate_reliability(list(stats.values()))
    # min(0.7, 0.375) = 0.375 ; min(10, 8) = 8
    assert out["reliability"] == pytest.approx(0.375, rel=1e-3)
    assert out["sample_size"] == 8
