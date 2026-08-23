from ari.events import SCHEMA_VERSION, Event, append_event, read_events


def test_append_then_read_round_trip(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_event(
        path,
        Event(
            ts="2026-08-23T14:02:11+08:00",
            type="batch_opened",
            batch="b3",
            payload={"hypothesis": "大模型更好"},
        ),
    )
    append_event(
        path,
        Event(
            ts="2026-08-23T14:05:00+08:00",
            type="prediction",
            batch="b3",
            run="lr=0.0001",
            payload={"metrics": {"acc": 0.8}},
        ),
    )

    events, errors = read_events(path)

    assert errors == []
    assert [e.type for e in events] == ["batch_opened", "prediction"]
    assert events[1].run == "lr=0.0001"
    assert events[1].payload["metrics"]["acc"] == 0.8
    assert events[0].v == SCHEMA_VERSION
    assert [e.line_no for e in events] == [1, 2]


def test_corrupt_line_is_skipped_and_reported(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(
        '{"v":1,"ts":"t1","type":"note","payload":{}}\n'
        "{ this is not json\n"
        '{"v":1,"ts":"t3","type":"note","payload":{}}\n',
        encoding="utf-8",
    )

    events, errors = read_events(path)

    assert [e.ts for e in events] == ["t1", "t3"]
    assert len(errors) == 1
    assert errors[0].line_no == 2


def test_line_missing_required_field_is_reported(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"v":1,"type":"note","payload":{}}\n', encoding="utf-8")

    events, errors = read_events(path)

    assert events == []
    assert len(errors) == 1
    assert "ts" in errors[0].reason


def test_blank_lines_are_ignored_without_error(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('\n{"v":1,"ts":"t1","type":"note","payload":{}}\n\n', encoding="utf-8")

    events, errors = read_events(path)

    assert len(events) == 1
    assert errors == []


def test_higher_schema_version_is_preserved_not_dropped(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"v":99,"ts":"t1","type":"future_type","payload":{}}\n', encoding="utf-8")

    events, errors = read_events(path)

    assert errors == []
    assert events[0].v == 99
    assert events[0].type == "future_type"


def test_missing_file_reads_as_empty(tmp_path):
    events, errors = read_events(tmp_path / "nope.jsonl")

    assert events == []
    assert errors == []


def test_unicode_is_written_unescaped(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_event(path, Event(ts="t1", type="note", payload={"text": "过拟合"}))

    assert "过拟合" in path.read_text(encoding="utf-8")
