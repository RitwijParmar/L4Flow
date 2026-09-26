import json

import pytest

from l4flow.workload import (
    WorkloadRow,
    generate_workload,
    load_workload,
    summarize_workload,
    write_workload,
)


def test_workload_is_deterministic_and_has_mixture():
    first = generate_workload(128, seed=7)
    second = generate_workload(128, seed=7)
    assert first == second
    summary = summarize_workload(first)
    assert summary["requests"] == 128
    assert set(summary["class_counts"]) == {"short", "medium", "long"}
    assert 0.5 < summary["shared_prefix_rate"] < 0.9


def test_workload_round_trip_and_duplicate_validation(tmp_path):
    path = tmp_path / "workload.jsonl"
    rows = generate_workload(3, seed=11)
    write_workload(path, rows)
    assert load_workload(path) == rows

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text("\n".join(json.dumps(row.__dict__) for row in rows[:2]).replace(
        rows[1].request_id, rows[0].request_id
    ) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate request_id"):
        load_workload(duplicate)


def test_workload_rejects_unknown_class():
    with pytest.raises(ValueError, match="unknown class"):
        WorkloadRow.from_mapping(
            {
                "request_id": "x",
                "workload_class": "unknown",
                "prompt": "hello",
                "max_new_tokens": 8,
                "prefix_id": "p",
            },
            line_number=1,
        )
