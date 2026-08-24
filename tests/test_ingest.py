import json

import pytest

from ari.ingest import (
    ParsedResult,
    build_manual_draft,
    compile_template,
    discover,
    parse_manual,
    parse_result_file,
)

RUNS = ["lr=0.001,model=base", "lr=0.0001,model=large"]
TEMPLATE = "logs/{model}_{lr}/s{seed}/results.json"


def _touch(root, relative, payload):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_template_reverse_parses_variables_and_seed():
    match = compile_template(TEMPLATE).match("logs/base_1e-3/s0/results.json")

    assert match.groupdict() == {"model": "base", "lr": "1e-3", "seed": "0"}


def test_template_without_seed_is_allowed():
    match = compile_template("out/{model}.json").match("out/large.json")

    assert match.groupdict() == {"model": "large"}


def test_template_variables_do_not_swallow_path_separators():
    assert compile_template(TEMPLATE).match("logs/a/b_1e-3/s0/results.json") is None


def test_discover_maps_files_onto_normalized_run_keys(tmp_path):
    _touch(tmp_path, "logs/base_1e-3/s0/results.json", {"top1_acc": 0.73})
    _touch(tmp_path, "logs/large_1e-4/s1/results.json", {"top1_acc": 0.88})

    found, unmatched = discover(tmp_path, TEMPLATE, RUNS)

    assert unmatched == []
    assert {(f.run, f.seed) for f in found} == {
        ("lr=0.001,model=base", 0),
        ("lr=0.0001,model=large", 1),
    }


def test_discover_reports_files_that_match_the_shape_but_not_any_run(tmp_path):
    _touch(tmp_path, "logs/huge_1e-3/s0/results.json", {"top1_acc": 0.9})

    found, unmatched = discover(tmp_path, TEMPLATE, RUNS)

    assert found == []
    assert len(unmatched) == 1
    assert "huge" in unmatched[0]


def test_discover_defaults_seed_to_zero_when_the_template_has_none(tmp_path):
    _touch(tmp_path, "out/base.json", {"top1_acc": 0.7})

    found, _ = discover(tmp_path, "out/{model}.json", ["model=base"])

    assert found[0].seed == 0


def test_parse_json_reads_flat_metrics(tmp_path):
    path = _touch(tmp_path, "r.json", {"top1_acc": 0.83, "train_loss": 0.31, "extra": 1})

    parsed = parse_result_file(path, ["top1_acc", "train_loss"])

    assert parsed.metrics == {"top1_acc": 0.83, "train_loss": 0.31}
    assert parsed.missing == []
    assert parsed.kind == "structured"


def test_parse_json_reads_one_level_of_nesting(tmp_path):
    path = _touch(tmp_path, "r.json", {"final": {"top1_acc": 0.83}})

    assert parse_result_file(path, ["top1_acc"]).metrics == {"top1_acc": 0.83}


def test_parse_json_supports_a_dotted_path(tmp_path):
    path = _touch(tmp_path, "r.json", {"eval": {"top1": {"acc": 0.83}}})

    assert parse_result_file(path, ["eval.top1.acc"]).metrics == {"eval.top1.acc": 0.83}


def test_missing_metric_is_reported_not_filled_in(tmp_path):
    path = _touch(tmp_path, "r.json", {"top1_acc": 0.83})

    parsed = parse_result_file(path, ["top1_acc", "train_loss"])

    assert parsed.metrics == {"top1_acc": 0.83}
    assert parsed.missing == ["train_loss"]


def test_non_numeric_value_is_reported_as_missing(tmp_path):
    path = _touch(tmp_path, "r.json", {"top1_acc": "N/A"})

    assert parse_result_file(path, ["top1_acc"]).missing == ["top1_acc"]


def test_parse_csv_takes_the_last_row(tmp_path):
    path = _touch(
        tmp_path,
        "m.csv",
        "epoch,top1_acc,train_loss\n1,0.70,0.90\n2,0.80,0.50\n3,0.83,0.31\n",
    )

    parsed = parse_result_file(path, ["top1_acc", "train_loss"])

    assert parsed.metrics == {"top1_acc": 0.83, "train_loss": 0.31}
    assert "最后一行" in parsed.note


def test_empty_csv_reports_every_metric_as_missing(tmp_path):
    path = _touch(tmp_path, "m.csv", "epoch,top1_acc\n")

    assert parse_result_file(path, ["top1_acc"]).missing == ["top1_acc"]


def test_unknown_extension_is_a_clear_error(tmp_path):
    path = _touch(tmp_path, "r.txt", "whatever")

    with pytest.raises(ValueError) as exc:
        parse_result_file(path, ["top1_acc"])

    assert ".txt" in str(exc.value)


def test_manual_draft_lists_every_run_and_metric():
    draft = build_manual_draft(RUNS, ["top1_acc"], batch_id="b1")

    for run in RUNS:
        assert run in draft
    assert "top1_acc" in draft
    assert "seed" in draft


MANUAL = """
results:
  - run: lr=0.001,model=base
    seed: 0
    top1_acc: 0.731
  - run: lr=0.001,model=base
    seed: 1
    top1_acc: 0.779
"""


def test_parse_manual_reads_one_entry_per_seed():
    parsed = parse_manual(MANUAL, RUNS, ["top1_acc"])

    assert len(parsed) == 2
    assert parsed[0].run == "lr=0.001,model=base"
    assert parsed[1].seed == 1
    assert parsed[1].metrics == {"top1_acc": 0.779}


def test_parse_manual_skips_entries_left_blank():
    text = MANUAL + "  - run: lr=0.0001,model=large\n    seed: 0\n    top1_acc:\n"

    assert len(parse_manual(text, RUNS, ["top1_acc"])) == 2


def test_parse_manual_rejects_an_unknown_run():
    text = "results:\n  - run: model=nope\n    seed: 0\n    top1_acc: 0.5\n"

    with pytest.raises(ValueError) as exc:
        parse_manual(text, RUNS, ["top1_acc"])

    assert "model=nope" in str(exc.value)


def test_parsed_result_carries_source_information(tmp_path):
    path = _touch(tmp_path, "r.json", {"top1_acc": 0.83})

    parsed = parse_result_file(path, ["top1_acc"])

    assert isinstance(parsed, ParsedResult)
    assert parsed.path == path
    assert parsed.mtime.endswith(("+00:00", "+08:00")) or "T" in parsed.mtime
