from ari.board import render_markdown
from ari.events import ParseError
from ari.project import project


def test_unreflected_surprise_is_pinned_above_the_batch_sections(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.950))

    output = render_markdown(batches, warnings, parse_errors=[])

    assert output.index("待复盘") < output.index("## 批次")


def test_no_failure_language_anywhere(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.950))

    # 含坏行报告一起检查：措辞要求覆盖看板的每一个角落
    output = render_markdown(
        batches, warnings, parse_errors=[ParseError(7, "JSON 格式不合法", "{ bad")]
    )

    for word in ("失败", "错误", "不及格", "糟糕"):
        assert word not in output


def test_confirmed_run_is_not_pinned(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.831))

    assert "待复盘" not in render_markdown(batches, warnings, parse_errors=[])


def test_low_information_signal_is_surfaced(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.831))

    assert "未产生新信息" in render_markdown(batches, warnings, parse_errors=[])


def test_parse_errors_are_reported_with_line_numbers(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.831))

    output = render_markdown(
        batches, warnings, parse_errors=[ParseError(7, "这一行读不出来", "{ bad")]
    )

    assert "第 7 行" in output


def test_integrity_flag_is_shown(make_events):
    batches, warnings = project(
        make_events(prediction=0.830, actual=0.831, result_mtime="2026-08-23T09:00:00+08:00")
    )

    assert "预测晚于结果" in render_markdown(batches, warnings, parse_errors=[])


def test_revised_prediction_is_marked(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.831, revise_to=0.831))

    assert "已修订" in render_markdown(batches, warnings, parse_errors=[])


def test_noisy_run_explains_why_no_conclusion(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=[0.80, 0.83, 0.86]))

    output = render_markdown(batches, warnings, parse_errors=[])

    assert "NOISY" in output
    assert "seed" in output


def test_research_direction_is_shown_when_present(make_events):
    events = make_events(prediction=0.830, actual=0.831)
    events[0] = type(events[0])(
        ts=events[0].ts,
        type=events[0].type,
        batch=events[0].batch,
        payload={**events[0].payload, "research_direction": "小数据集上的模型正则化"},
    )
    batches, warnings = project(events)

    output = render_markdown(batches, warnings, parse_errors=[])

    assert "研究方向" in output
    assert "小数据集上的模型正则化" in output
