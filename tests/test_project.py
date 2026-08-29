from conftest import make_batch_opened, make_prediction, make_result

from ari.events import Event
from ari.project import closure_blockers, project
from ari.verdict import Verdict


def test_hypothesis_is_snapshotted_on_the_batch():
    batches, _ = project([make_batch_opened()])

    assert batches["b1"].hypothesis == "large 比 base 好"


def test_prediction_and_result_produce_a_verdict():
    batches, _ = project(
        [
            make_batch_opened(),
            make_prediction("model=large", {"top1_acc": 0.830}),
            make_result("model=large", {"top1_acc": 0.831}),
        ]
    )

    run = batches["b1"].runs["model=large"]
    assert run.verdict is Verdict.CONFIRMED
    assert run.aggregates["top1_acc"].n == 1


def test_multiple_seeds_aggregate_into_one_run():
    batches, _ = project(
        [
            make_batch_opened(),
            make_prediction("model=large", {"top1_acc": 0.830}),
            make_result("model=large", {"top1_acc": 0.828}, seed=0),
            make_result("model=large", {"top1_acc": 0.832}, seed=1),
        ]
    )

    run = batches["b1"].runs["model=large"]
    assert run.aggregates["top1_acc"].n == 2


def test_duplicate_prediction_is_rejected_and_warned():
    batches, _ = project(
        [
            make_batch_opened(),
            make_prediction("model=large", {"top1_acc": 0.830}),
            make_prediction("model=large", {"top1_acc": 0.900}),
        ]
    )

    run = batches["b1"].runs["model=large"]
    assert run.prediction["metrics"]["top1_acc"] == 0.830
    assert any("重复" in w for w in run.warnings)


def test_revision_keeps_the_original_and_marks_revised():
    batches, _ = project(
        [
            make_batch_opened(),
            make_prediction("model=large", {"top1_acc": 0.830}),
            Event(
                ts="2026-08-23T10:30:00+08:00",
                type="prediction_revised",
                batch="b1",
                run="model=large",
                payload={"metrics": {"top1_acc": 83.0}, "rationale": "单位写错了"},
            ),
        ]
    )

    run = batches["b1"].runs["model=large"]
    assert run.revised is True
    assert run.prediction["metrics"]["top1_acc"] == 83.0
    assert run.original_prediction["metrics"]["top1_acc"] == 0.830


def test_result_older_than_prediction_is_flagged():
    batches, _ = project(
        [
            make_batch_opened(),
            make_prediction("model=large", {"top1_acc": 0.830}, ts="2026-08-23T10:05:00+08:00"),
            make_result("model=large", {"top1_acc": 0.831}, mtime="2026-08-23T09:00:00+08:00"),
        ]
    )

    assert "result_predates_prediction" in batches["b1"].runs["model=large"].integrity


def test_result_without_prediction_is_unverified_not_awaiting_result():
    """有实测值却没有预测，不能显示成「等待结果」——事实相反。

    judge_run({}, ...) 返回 NO_RESULT 是纯内核的正确契约（没有预测就没有
    可判定的东西），但投影层不能就这么交出去：这个 run 明明有数，而
    closure_blockers 还会报「还有 run 尚无结果」。
    """
    batches, _ = project([make_batch_opened(), make_result("model=large", {"top1_acc": 0.81})])

    run = batches["b1"].runs["model=large"]
    assert run.verdict is Verdict.UNVERIFIED
    assert "result_without_prediction" in run.integrity
    assert run.aggregates["top1_acc"].mean == 0.81


def test_prediction_arriving_after_a_result_is_flagged_permanently():
    """预测晚于结果入库 → 永久标记，且不依赖文件 mtime。

    这里故意让 mtime（14:00）晚于预测时间戳（13:00），使既有的
    result_predates_prediction 检查**不会**触发。事件顺序本身就是证据，
    touch 一下文件绕不过去。
    """
    batches, _ = project(
        [
            make_batch_opened(),
            make_result("model=large", {"top1_acc": 0.81}, mtime="2026-08-23T14:00:00+08:00"),
            make_prediction(
                "model=large", {"top1_acc": 0.830}, ts="2026-08-23T13:00:00+08:00"
            ),
        ]
    )

    run = batches["b1"].runs["model=large"]
    assert "prediction_after_result" in run.integrity
    assert "result_predates_prediction" not in run.integrity
    # 预测仍然入库、仍然参与判定——不拒绝数据，只永久记录顺序。
    assert run.prediction["metrics"]["top1_acc"] == 0.830
    assert run.verdict is Verdict.SURPRISE


def test_prediction_before_result_is_not_flagged():
    batches, _ = project(
        [
            make_batch_opened(),
            make_prediction("model=large", {"top1_acc": 0.830}),
            make_result("model=large", {"top1_acc": 0.831}),
        ]
    )

    assert batches["b1"].runs["model=large"].integrity == []


def test_closure_blockers_names_the_missing_prediction():
    """收口阻塞原因要说实话：是预测缺席，不是「还有结果待确认」。"""
    batches, _ = project([make_batch_opened(), make_result("model=large", {"top1_acc": 0.81})])

    blockers = closure_blockers(batches["b1"])
    assert blockers == ["还有 run 的结果先到、预测缺席"]


def test_batch_meta_can_be_revised_after_opening():
    """result_path 与 expected_ranking 可以在批次开启后补填。"""
    batches, warnings = project(
        [
            make_batch_opened(),
            Event(
                ts="2026-08-23T11:00:00+08:00",
                type="batch_meta_revised",
                batch="b1",
                payload={
                    "result_path": "logs/{model}/s{seed}/results.json",
                    "expected_ranking": {"metric": "top1_acc", "order": ["model=large"]},
                },
            ),
        ]
    )

    batch = batches["b1"]
    assert batch.result_path == "logs/{model}/s{seed}/results.json"
    assert batch.expected_ranking == {"metric": "top1_acc", "order": ["model=large"]}
    assert warnings == []


def test_batch_meta_revision_only_touches_given_fields():
    batches, _ = project(
        [
            make_batch_opened(result_path="logs/old.json"),
            Event(
                ts="2026-08-23T11:00:00+08:00",
                type="batch_meta_revised",
                batch="b1",
                payload={"expected_ranking": {"metric": "top1_acc", "order": []}},
            ),
        ]
    )

    assert batches["b1"].result_path == "logs/old.json"


def test_paper_events_do_not_leak_into_batch_warnings():
    """论文事件属于独立投影，保存章节不能伪装成「未开启批次」事件。"""
    batches, warnings = project(
        [
            Event(
                ts="2026-08-23T11:00:00+08:00",
                type="draft_opened",
                payload={"draft": "p1", "title": "论文"},
            ),
            Event(
                ts="2026-08-23T11:01:00+08:00",
                type="section_saved",
                payload={"draft": "p1", "section": "intro", "text": "正文"},
            ),
            Event(
                ts="2026-08-23T11:02:00+08:00",
                type="draft_status_changed",
                payload={"draft": "p1", "status": "writing"},
            ),
        ]
    )

    assert batches == {}
    assert warnings == []


def test_surprise_run_needs_its_own_reflection_to_close():
    events = [
        make_batch_opened(),
        make_prediction("model=large", {"top1_acc": 0.830}),
        make_result("model=large", {"top1_acc": 0.950}),
        Event(
            ts="2026-08-23T13:00:00+08:00",
            type="reflection",
            batch="b1",
            payload={"scope": "batch", "text": "整体收口"},
        ),
    ]

    batches, _ = project(events)
    run = batches["b1"].runs["model=large"]
    assert run.verdict is Verdict.SURPRISE
    assert run.closed is False
    assert batches["b1"].closed is False

    events.append(
        Event(
            ts="2026-08-23T13:10:00+08:00",
            type="reflection",
            batch="b1",
            run="model=large",
            payload={"scope": "run", "text": "数据增强没关"},
        )
    )
    batches, _ = project(events)
    assert batches["b1"].runs["model=large"].closed is True
    assert batches["b1"].closed is True


def test_confirmed_run_closes_via_batch_reflection():
    batches, _ = project(
        [
            make_batch_opened(),
            make_prediction("model=large", {"top1_acc": 0.830}),
            make_result("model=large", {"top1_acc": 0.831}),
            Event(
                ts="2026-08-23T13:00:00+08:00",
                type="reflection",
                batch="b1",
                payload={"scope": "batch", "text": "符合预期"},
            ),
        ]
    )

    assert batches["b1"].runs["model=large"].closed is True


def test_batch_reflection_does_not_close_a_run_with_no_result():
    batches, _ = project(
        [
            make_batch_opened(),
            make_prediction("model=large", {"top1_acc": 0.830}),
            Event(
                ts="2026-08-23T13:00:00+08:00",
                type="reflection",
                batch="b1",
                payload={"scope": "batch", "text": "过早收口"},
            ),
        ]
    )

    assert batches["b1"].runs["model=large"].verdict is Verdict.NO_RESULT
    assert batches["b1"].closed is False


def test_all_confirmed_batch_raises_the_low_information_signal():
    batches, _ = project(
        [
            make_batch_opened(),
            make_prediction("model=base", {"top1_acc": 0.800}),
            make_prediction("model=large", {"top1_acc": 0.830}),
            make_result("model=base", {"top1_acc": 0.801}),
            make_result("model=large", {"top1_acc": 0.831}),
        ]
    )

    assert batches["b1"].info_signal is not None


def test_ranking_is_judged_at_batch_level():
    batches, _ = project(
        [
            make_batch_opened(
                expected_ranking={
                    "metric": "top1_acc",
                    "order": ["model=large", "model=base"],
                }
            ),
            make_prediction("model=base", {"top1_acc": 0.800}),
            make_prediction("model=large", {"top1_acc": 0.830}),
            make_result("model=base", {"top1_acc": 0.860}),
            make_result("model=large", {"top1_acc": 0.801}),
        ]
    )

    assert batches["b1"].ranking.verdict is Verdict.SURPRISE


def test_unknown_event_type_is_warned_not_fatal():
    batches, warnings = project(
        [
            make_batch_opened(),
            Event(ts="2026-08-23T14:00:00+08:00", type="from_the_future", batch="b1",
                  v=99, payload={}),
        ]
    )

    assert "b1" in batches
    assert any("from_the_future" in w for w in warnings)


def test_event_for_unopened_batch_is_warned():
    batches, warnings = project([make_prediction("model=large", {"top1_acc": 0.8})])

    assert batches == {}
    assert any("b1" in w for w in warnings)
