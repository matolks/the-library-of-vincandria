from __future__ import annotations

import pytest

from pipeline import mapper


def test_resolve_cycles_drops_lowest_confidence_edge_until_acyclic():
    edges = [
        mapper.Edge("a", "b", 0.90, "a before b"),
        mapper.Edge("b", "a", 0.65, "weak reverse edge"),
        mapper.Edge("c", "d", 0.88, "c before d"),
        mapper.Edge("d", "c", 0.60, "weak reverse edge"),
    ]

    resolved, dropped = mapper.resolve_cycles(
        edges,
        id_to_slug={"a": "a", "b": "b", "c": "c", "d": "d"},
    )

    assert mapper.detect_cycle(resolved) is None
    assert {(edge.from_id, edge.to_id) for edge in dropped} == {
        ("b", "a"),
        ("d", "c"),
    }
    assert {(edge.from_id, edge.to_id) for edge in resolved} == {
        ("a", "b"),
        ("c", "d"),
    }


def test_resolve_cycles_drops_known_edges_before_cycle_detection():
    edges = [
        mapper.Edge("seed", "seed_target", 0.91, "seeded false positive"),
        mapper.Edge("audit", "audit_target", 0.88, "audited drop"),
        mapper.Edge("a", "b", 0.93, "keep"),
    ]

    resolved, dropped = mapper.resolve_cycles(
        edges,
        id_to_slug={
            "seed": "os-consistency-checking",
            "seed_target": "os-malloc",
            "audit": "os-filesystems",
            "audit_target": "os-io-devices",
            "a": "os-hard-drives",
            "b": "os-ssds",
        },
    )

    assert {(edge.from_id, edge.to_id) for edge in resolved} == {("a", "b")}
    assert {
        (edge.from_id, edge.to_id, edge.drop_type)
        for edge in dropped
    } == {
        ("seed", "seed_target", "manual_seed"),
        ("audit", "audit_target", "audited_drop"),
    }


def test_resolve_cycles_drops_reverse_of_protected_edge_before_cycle_detection():
    edges = [
        mapper.Edge("faulting", "updates", 0.85, "protected keep"),
        mapper.Edge("updates", "faulting", 0.92, "strong reverse edge"),
    ]

    resolved, dropped = mapper.resolve_cycles(
        edges,
        id_to_slug={
            "faulting": "os-page-faulting",
            "updates": "os-page-table-updates",
        },
    )

    assert {(edge.from_id, edge.to_id) for edge in resolved} == {
        ("faulting", "updates")
    }
    assert [
        (edge.from_id, edge.to_id, edge.drop_type, edge.reason, edge.confidence)
        for edge in dropped
    ] == [
        (
            "updates",
            "faulting",
            "reverse_protected",
            "spurious reverse of protected prerequisite",
            0.92,
        )
    ]


def test_resolve_cycles_drops_lower_confidence_mutual_edge_before_cycle_detection():
    edges = [
        mapper.Edge("processes", "syscalls", 0.85, "abstraction before mechanism"),
        mapper.Edge("syscalls", "processes", 0.75, "process api uses fork/exec"),
    ]

    resolved, dropped = mapper.resolve_cycles(
        edges,
        id_to_slug={
            "processes": "os-processes-threads",
            "syscalls": "os-kernel-syscalls",
        },
    )

    assert {(edge.from_id, edge.to_id) for edge in resolved} == {
        ("processes", "syscalls")
    }
    assert [
        (edge.from_id, edge.to_id, edge.drop_type, edge.reason, edge.confidence)
        for edge in dropped
    ] == [
        (
            "syscalls",
            "processes",
            "mutual_lower_confidence",
            "process api uses fork/exec",
            0.75,
        )
    ]


def test_resolve_cycles_raises_when_remaining_cycle_edges_are_above_floor():
    edges = [
        mapper.Edge("a", "b", 0.85, "keep"),
        mapper.Edge("b", "c", 0.91, "keep"),
        mapper.Edge("c", "a", 0.88, "keep"),
    ]

    with pytest.raises(mapper.CycleUnresolved, match="a -> b -> c -> a"):
        mapper.resolve_cycles(
            edges,
            id_to_slug={
                "a": "a",
                "b": "b",
                "c": "c",
            },
        )
