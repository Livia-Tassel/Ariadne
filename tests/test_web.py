"""v0.2 GUI 的应用服务与本地 HTTP 入口。"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from typer.testing import CliRunner

from ari import cli, web
from ari.web import GuiInputError, GuiService, make_server


# CI/开发机可能全局配置 HTTP 代理；localhost 测试必须绕过它。
_open = build_opener(ProxyHandler({})).open


def _batch_payload():
    return {
        "research_direction": "小数据集上的模型正则化",
        "hypothesis": "large 模型更受益于增强",
        "dimensions": [{"name": "model", "values": ["base", "large"]}],
        "metrics": [
            {
                "name": "top1_acc",
                "direction": "higher_better",
                "compare": "absolute",
                "tolerance": 0.005,
            }
        ],
        "predictions": [
            {
                "run": "model=base",
                "metrics": {"top1_acc": "0.80 ~ 0.82"},
                "confidence": "high",
                "rationale": "稳定基线",
            },
            {
                "run": "model=large",
                "metrics": {"top1_acc": "0.83"},
                "confidence": "medium",
                "rationale": "容量更大",
            },
        ],
    }


def _add_results(service):
    return service.add_results(
        {
            "batch": "b1",
            "rows": [
                {"run": "model=base", "seed": 0, "metrics": {"top1_acc": 0.81}},
                {"run": "model=large", "seed": 0, "metrics": {"top1_acc": 0.95}},
            ],
        }
    )


def test_gui_opens_an_empty_directory_without_running_init(tmp_path):
    root = tmp_path / "new-project"
    service = GuiService(root)

    state = service.state()

    assert state["project"]["path"] == str(root)
    assert state["summary"]["batches"] == 0
    assert (root / "runs.jsonl").exists()
    assert (root / "config.toml").exists()
    assert (root / "logs").is_dir()


def test_gui_full_loop_creates_results_reviews_beliefs_and_closes(tmp_path):
    service = GuiService(tmp_path / "exp")

    preview = service.preview_runs(_batch_payload())
    assert preview["runs"] == ["model=base", "model=large"]

    created = service.create_batch(_batch_payload())
    assert created == {"ok": True, "batch": "b1", "run_count": 2}

    state = service.state()
    batch = state["batches"][0]
    assert batch["research_direction"] == "小数据集上的模型正则化"
    assert batch["runs"][0]["prediction"]["metrics"]["top1_acc"] == [0.8, 0.82]

    assert _add_results(service)["written"] == 2
    state = service.state()
    assert state["summary"]["pending_reviews"] == 1
    assert state["pending_reviews"][0]["run"] == "model=large"

    with pytest.raises(GuiInputError, match="SURPRISE 未复盘"):
        service.close_batch({"batch": "b1", "cause": "过早收口"})

    reviewed = service.add_review(
        {
            "batch": "b1",
            "run": "model=large",
            "cause": "增强配置没有对齐",
            "next": "固定增强后重跑",
            "beliefs_added": "增强是这个设置下的主要混淆因素",
        }
    )
    assert reviewed["written"] == 2
    assert service.state()["beliefs"][0]["text"] == "增强是这个设置下的主要混淆因素"

    closed = service.close_batch(
        {"batch": "b1", "cause": "容量判断暂时保留，先排除增强", "next": "开 b2"}
    )
    assert closed["written"] == 1
    assert service.state()["batches"][0]["closed"] is True


def test_gui_rejects_duplicate_seed_instead_of_silently_overwriting(tmp_path):
    service = GuiService(tmp_path / "exp")
    service.create_batch(_batch_payload())
    _add_results(service)

    with pytest.raises(GuiInputError, match="seed=0 已经存在"):
        service.add_results(
            {
                "batch": "b1",
                "rows": [
                    {"run": "model=base", "seed": 0, "metrics": {"top1_acc": 0.99}}
                ],
            }
        )


def test_gui_does_not_close_a_batch_with_no_results(tmp_path):
    service = GuiService(tmp_path / "exp")
    service.create_batch(_batch_payload())

    with pytest.raises(GuiInputError, match="尚无结果"):
        service.close_batch({"batch": "b1", "cause": "还没跑也不该收口"})


def test_gui_validates_dimensions_predictions_and_metric_specs(tmp_path):
    service = GuiService(tmp_path / "exp")

    with pytest.raises(GuiInputError, match="重复取值"):
        service.preview_runs({"dimensions": [{"name": "model", "values": "base,base"}]})

    payload = _batch_payload()
    payload["predictions"][0]["rationale"] = ""
    with pytest.raises(GuiInputError, match="预测理由"):
        service.create_batch(payload)

    payload = _batch_payload()
    payload["metrics"][0]["tolerance"] = -1
    with pytest.raises(GuiInputError, match="规格有问题"):
        service.create_batch(payload)


@pytest.fixture
def http_gui(tmp_path):
    try:
        server = make_server(tmp_path / "http-project", port=0)
    except PermissionError:
        pytest.skip("当前沙箱禁止绑定本地端口；普通开发环境与 CI 会执行此测试")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post(url, payload):
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _open(request, timeout=3) as response:
        return response.status, json.loads(response.read())


def test_http_server_serves_the_app_and_json_api(http_gui):
    with _open(http_gui + "/", timeout=3) as response:
        html = response.read().decode()
        assert response.status == 200
        assert "Ariadne" in html
        assert "账本" in html

    # 前端是 ES 模块，子目录必须能取到，否则页面整个起不来。
    with _open(http_gui + "/lib/dom.js", timeout=3) as response:
        assert response.status == 200
        assert "export" in response.read().decode()

    with _open(http_gui + "/api/state", timeout=3) as response:
        state = json.loads(response.read())
        assert state["summary"]["runs"] == 0

    status, result = _post(
        http_gui + "/api/runs/preview",
        {"dimensions": [{"name": "lr", "values": ["1e-4", "0.001"]}]},
    )
    assert status == 200
    assert result["runs"] == ["lr=0.0001", "lr=0.001"]


def test_http_validation_error_is_json(http_gui):
    request = Request(
        http_gui + "/api/runs/preview",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc:
        _open(request, timeout=3)
    assert exc.value.code == 400
    body = json.loads(exc.value.read())
    assert body["ok"] is False
    assert "变量维度" in body["error"]


def test_gui_cli_delegates_to_local_server(tmp_path, monkeypatch):
    called = {}

    def fake_serve(project_dir, **options):
        called["project"] = project_dir
        called.update(options)

    monkeypatch.setattr(web, "serve", fake_serve)
    result = CliRunner().invoke(
        cli.app,
        ["gui", "-p", str(tmp_path / "demo"), "--port", "0", "--no-open"],
    )

    assert result.exit_code == 0
    assert called == {
        "project": tmp_path / "demo",
        "host": "127.0.0.1",
        "port": 0,
        "open_browser": False,
    }


def test_batch_can_declare_result_path_and_expected_ranking(tmp_path):
    """GUI 建的批次此前永远拿不到这两样：web.py 把它们写死成 None。

    后果不是「少个便利功能」：_check_integrity 依赖结果文件的 mtime，而
    mtime 只存在于按 result_path 自动发现的路径上，所以 GUI 建的批次拿不到
    「先看结果再补预测」的检查。expected_ranking 同理让排序判定永不执行。
    """
    service = GuiService(tmp_path / "p")
    payload = _batch_payload()
    payload["result_path"] = "logs/{model}/s{seed}/results.json"
    payload["expected_ranking"] = {"metric": "top1_acc", "order": ["model=large", "model=base"]}

    service.create_batch(payload)

    batch = service.state()["batches"][0]
    assert batch["result_path"] == "logs/{model}/s{seed}/results.json"
    assert batch["ranking"] is not None  # 排序判定不再是死代码


def test_result_path_is_optional(tmp_path):
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())

    assert service.state()["batches"][0]["result_path"] is None


def test_results_carry_their_source_file_and_trigger_the_integrity_check(tmp_path):
    """结果带上来源文件后，mtime 早于预测就该被标记。

    手工录入没有 mtime，因此拿不到这个检查——这正是自动发现必须成为
    主路径的原因，不只是为了少敲几个字。
    """
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())
    service.add_results(
        {
            "batch": "b1",
            "rows": [
                {
                    "run": "model=base",
                    "seed": 0,
                    "metrics": {"top1_acc": 0.81},
                    "source": {
                        "path": "logs/base/s0/results.json",
                        "mtime": "2020-01-01T00:00:00+08:00",
                    },
                }
            ],
        }
    )

    run = next(
        r for r in service.state()["batches"][0]["runs"] if r["run"] == "model=base"
    )
    assert "result_predates_prediction" in run["integrity"]


def test_manual_results_still_record_that_they_were_typed_by_hand(tmp_path):
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())
    _add_results(service)

    events, *_ = service._load()
    source = next(e for e in events if e.type == "run_result").payload["source"]
    assert source["kind"] == "manual_gui"
    assert source["mtime"] is None


def test_batch_meta_can_be_revised_after_creation(tmp_path):
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())

    service.revise_batch_meta(
        {"batch": "b1", "result_path": "logs/{model}/s{seed}/results.json"}
    )

    assert (
        service.state()["batches"][0]["result_path"] == "logs/{model}/s{seed}/results.json"
    )


def test_revising_meta_of_an_unknown_batch_is_rejected(tmp_path):
    service = GuiService(tmp_path / "p")

    with pytest.raises(GuiInputError):
        service.revise_batch_meta({"batch": "nope", "result_path": "logs/x.json"})


@pytest.mark.parametrize(
    "url_path, expected",
    [
        ("/", "index.html"),
        ("/index.html", "index.html"),
        ("/app.js", "app.js"),
        ("/styles.css", "styles.css"),
        ("/lib/dom.js", "lib/dom.js"),
        ("/views/today.js", "views/today.js"),
    ],
)
def test_static_paths_inside_webui_are_served(url_path, expected):
    assert web._static_target(url_path) == expected


@pytest.mark.parametrize(
    "url_path",
    [
        "/../web.py",                 # 上跳一级
        "/lib/../../web.py",          # 中途上跳
        "/./app.js",                  # 单点段
        "/..%2fweb.py",               # 百分号编码；urlsplit 不解码，字符集就该拦住
        "/lib/dom.js/../../secrets",  # 尾段不是白名单后缀
        "/config.toml",               # 后缀不在白名单
        "/app.py",                    # 同上，且是源码
        "//etc/passwd",               # 空段
        "/lib\\dom.js",               # 反斜杠
        "app.js",                     # 不以 / 开头
        "/",                          # 兜底见上，这里确保下面的断言不误判
    ][:-1],
)
def test_static_paths_outside_webui_are_refused(url_path):
    assert web._static_target(url_path) is None


def _batch_with_files(tmp_path, template="logs/{model}/s{seed}/results.json"):
    """建一个声明了 result_path 的批次，并在项目里放两个结果文件。"""
    root = tmp_path / "p"
    service = GuiService(root)
    payload = _batch_payload()
    payload["result_path"] = template
    service.create_batch(payload)

    def write(relative, body):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    write("logs/base/s0/results.json", {"top1_acc": 0.81})
    write("logs/large/s0/results.json", {"metrics": {"top1_acc": 0.84}})
    return service, root, write


def test_discover_finds_result_files_by_template(tmp_path):
    """自动发现是主路径：结果形态就是每个 run 一个 JSON。"""
    service, _, _ = _batch_with_files(tmp_path)

    result = service.discover_results({"batch": "b1"})

    rows = {row["run"]: row for row in result["found"]}
    assert set(rows) == {"model=base", "model=large"}
    assert rows["model=base"]["metrics"] == {"top1_acc": 0.81}
    # 嵌套一层也能取到——parse_result_file 会往下找一层同名键。
    assert rows["model=large"]["metrics"] == {"top1_acc": 0.84}
    assert rows["model=base"]["seed"] == 0
    assert rows["model=base"]["source"]["path"] == "logs/base/s0/results.json"
    assert rows["model=base"]["source"]["mtime"]
    assert result["unmatched"] == []
    assert result["errors"] == []


def test_discover_writes_nothing(tmp_path):
    """只读。抽到的东西要先给人看一眼再确认——错的指标进表比缺失更有害。"""
    service, _, _ = _batch_with_files(tmp_path)
    before = service.runs_path.read_text(encoding="utf-8")

    service.discover_results({"batch": "b1"})

    assert service.runs_path.read_text(encoding="utf-8") == before


def test_discover_reports_files_that_match_the_template_but_no_run(tmp_path):
    """模板对得上却不属于任何 run：多半是模板写错了，或跑了计划外的配置。"""
    service, _, write = _batch_with_files(tmp_path)
    write("logs/xlarge/s0/results.json", {"top1_acc": 0.9})

    result = service.discover_results({"batch": "b1"})

    assert result["unmatched"] == ["logs/xlarge/s0/results.json"]
    assert len(result["found"]) == 2


def test_discover_reports_unreadable_files_without_losing_the_others(tmp_path):
    """一个文件坏了不该让整次发现失败——其余的照常抽出来。"""
    service, root, _ = _batch_with_files(tmp_path)
    (root / "logs/base/s0/results.json").write_text("{ 这不是 json", encoding="utf-8")

    result = service.discover_results({"batch": "b1"})

    assert [row["run"] for row in result["found"]] == ["model=large"]
    assert len(result["errors"]) == 1
    assert result["errors"][0]["path"] == "logs/base/s0/results.json"


def test_discover_reports_metrics_the_file_does_not_contain(tmp_path):
    """取不到的指标明确报告，不填空。"""
    service, root, _ = _batch_with_files(tmp_path)
    (root / "logs/base/s0/results.json").write_text(json.dumps({"other": 1}), encoding="utf-8")

    row = next(r for r in service.discover_results({"batch": "b1"})["found"] if r["run"] == "model=base")

    assert row["missing"] == ["top1_acc"]


def test_discover_marks_seeds_already_in_the_ledger(tmp_path):
    """已经录过的 seed 要标出来，否则确认表会诱导用户提交一次必然失败的写入。"""
    service, _, _ = _batch_with_files(tmp_path)
    service.add_results(
        {"batch": "b1", "rows": [{"run": "model=base", "seed": 0, "metrics": {"top1_acc": 0.81}}]}
    )

    rows = {row["run"]: row for row in service.discover_results({"batch": "b1"})["found"]}

    assert rows["model=base"]["existing"] is True
    assert rows["model=large"]["existing"] is False


def test_discover_needs_a_result_path(tmp_path):
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())

    with pytest.raises(GuiInputError) as exc:
        service.discover_results({"batch": "b1"})
    assert "result_path" in str(exc.value) or "路径模板" in str(exc.value)


def test_discovered_results_keep_the_integrity_check_alive(tmp_path):
    """发现 → 确认 → 入库这条路走完，mtime 早于预测就该被标记。

    这正是自动发现必须是主路径的原因：手敲没有 mtime，也就没有这个检查。
    """
    service, root, _ = _batch_with_files(tmp_path)
    old = datetime(2020, 1, 1).timestamp()
    os.utime(root / "logs/base/s0/results.json", (old, old))

    found = service.discover_results({"batch": "b1"})["found"]
    service.add_results({"batch": "b1", "rows": found})

    run = next(r for r in service.state()["batches"][0]["runs"] if r["run"] == "model=base")
    assert "result_predates_prediction" in run["integrity"]


def _bare_batch(service):
    """最小可提交的批次：假设 + 变量 + 指标，不含任何预测。"""
    payload = _batch_payload()
    payload.pop("predictions")
    return service.create_batch(payload)


def test_batch_can_open_without_any_prediction(tmp_path):
    """渐进锁定：约束是逐 run 的——某个 run 的预测先于它的结果就够了，
    不需要一次锁完整批。旧版把 24 个输入框堆在跑任何实验之前。"""
    service = GuiService(tmp_path / "p")

    assert _bare_batch(service) == {"ok": True, "batch": "b1", "run_count": 2}

    batch = service.state()["batches"][0]
    assert batch["runs"] == []
    assert batch["unlocked"] == ["model=base", "model=large"]


def test_predictions_are_locked_one_run_at_a_time(tmp_path):
    service = GuiService(tmp_path / "p")
    _bare_batch(service)

    service.lock_predictions(
        {
            "batch": "b1",
            "predictions": [
                {
                    "run": "model=base",
                    "metrics": {"top1_acc": "0.80 ~ 0.82"},
                    "confidence": "high",
                    "rationale": "稳定基线",
                }
            ],
        }
    )

    batch = service.state()["batches"][0]
    assert [run["run"] for run in batch["runs"]] == ["model=base"]
    assert batch["unlocked"] == ["model=large"]
    assert batch["runs"][0]["prediction"]["metrics"]["top1_acc"] == [0.8, 0.82]


def test_locking_a_run_twice_is_refused_visibly(tmp_path):
    """投影层对重复 prediction 只往 run.warnings 里塞一句，界面看不见。
    接口必须自己拦住并说清楚。"""
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())

    with pytest.raises(GuiInputError, match="已经锁定"):
        service.lock_predictions(
            {
                "batch": "b1",
                "predictions": [
                    {
                        "run": "model=base",
                        "metrics": {"top1_acc": "0.9"},
                        "rationale": "想改一下",
                    }
                ],
            }
        )


def test_locking_a_run_outside_the_batch_is_refused(tmp_path):
    service = GuiService(tmp_path / "p")
    _bare_batch(service)

    with pytest.raises(GuiInputError, match="不属于"):
        service.lock_predictions(
            {
                "batch": "b1",
                "predictions": [
                    {"run": "model=xlarge", "metrics": {"top1_acc": "0.9"}, "rationale": "手滑"}
                ],
            }
        )


def test_results_are_accepted_for_a_run_with_no_prediction(tmp_path):
    """永不拒绝真实测量。

    事件流是只追加的唯一真相，拒绝写入一次真实的实验结果比记录下它更糟。
    但这个 run 无法判定，而且必须在界面上响。
    """
    service = GuiService(tmp_path / "p")
    _bare_batch(service)

    service.add_results(
        {"batch": "b1", "rows": [{"run": "model=base", "seed": 0, "metrics": {"top1_acc": 0.81}}]}
    )

    run = next(r for r in service.state()["batches"][0]["runs"] if r["run"] == "model=base")
    assert run["verdict"] == "UNVERIFIED"
    assert "result_without_prediction" in run["integrity"]


def test_a_prediction_locked_after_the_result_carries_the_mark_forever(tmp_path):
    """不阻止你事后补预测，但那条记录会一直带着这个标记。"""
    service = GuiService(tmp_path / "p")
    _bare_batch(service)
    service.add_results(
        {"batch": "b1", "rows": [{"run": "model=base", "seed": 0, "metrics": {"top1_acc": 0.81}}]}
    )

    service.lock_predictions(
        {
            "batch": "b1",
            "predictions": [
                {"run": "model=base", "metrics": {"top1_acc": "0.81"}, "rationale": "马后炮"}
            ],
        }
    )

    run = next(r for r in service.state()["batches"][0]["runs"] if r["run"] == "model=base")
    assert "prediction_after_result" in run["integrity"]
    assert run["verdict"] == "CONFIRMED"  # 判定照常算，标记独立存在


def test_results_still_refuse_a_run_outside_the_batch(tmp_path):
    service = GuiService(tmp_path / "p")
    _bare_batch(service)

    with pytest.raises(GuiInputError, match="不属于批次"):
        service.add_results(
            {"batch": "b1", "rows": [{"run": "model=xlarge", "seed": 0, "metrics": {"top1_acc": 0.8}}]}
        )


def test_run_count_is_not_double_counted(tmp_path):
    """一个有结果但没锁预测的 run 会同时出现在 runs 与 unlocked 里，
    界面上把两者相加就会多算。总数以变量组合展开为准。"""
    service = GuiService(tmp_path / "p")
    _bare_batch(service)
    service.add_results(
        {"batch": "b1", "rows": [{"run": "model=base", "seed": 0, "metrics": {"top1_acc": 0.81}}]}
    )

    batch = service.state()["batches"][0]
    assert batch["run_count"] == 2
    assert len(batch["runs"]) == 1
    assert batch["unlocked"] == ["model=base", "model=large"]


# ---------- AI 那一层 ----------
#
# 整层可选。不配 config.toml、不设 key、断网，GUI 的行为都不变——只是少了
# AI 那一段：不报错、不阻断、不需要加任何 flag。

_FAKE_ADVICE = {
    "ranking": ["model=large", "model=base"],
    "directions": [{"variable": "model", "effect": "容量更大通常更好，但小数据上收益递减"}],
    "confounders": ["两组的数据增强配置是否一致"],
}


def test_advice_degrades_quietly_with_no_config(tmp_path):
    """没有 config.toml：返回 200 + available=false，不是错误。

    降级不是失败。界面显示一行安静的说明，而不是红色报错。
    """
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())
    (service.root / "config.toml").unlink()

    result = service.ask_advice({"batch": "b1"})

    assert result["ok"] is True
    assert result["available"] is False
    assert result["reason"]
    assert not [e for e in service._load()[0] if e.type == "note"]


def test_advice_is_archived_as_a_note_and_never_touches_verdicts(tmp_path, monkeypatch):
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())
    _add_results(service)
    before = [r["verdict"] for r in service.state()["batches"][0]["runs"]]

    monkeypatch.setattr(web, "advise", lambda root, design, runs: _FAKE_ADVICE)
    result = service.ask_advice({"batch": "b1"})

    assert result["available"] is True
    assert result["advice"]["ranking"] == ["model=large", "model=base"]

    notes = [e for e in service._load()[0] if e.type == "note"]
    assert len(notes) == 1
    assert notes[0].payload["kind"] == "ai_advice"
    assert [r["verdict"] for r in service.state()["batches"][0]["runs"]] == before


def test_advice_is_refused_before_any_prediction_is_locked(tmp_path, monkeypatch):
    """锚定效应是硬约束。

    先看到 AI 的判断，你自己的预测就失去了独立性——而独立性正是这套机制
    价值的来源。所以不是「先算好、晚点再显示」，是那时候根本还没算。
    """
    service = GuiService(tmp_path / "p")
    _bare_batch(service)

    monkeypatch.setattr(web, "advise", lambda *a: pytest.fail("锁定之前不该发起调用"))
    with pytest.raises(GuiInputError, match="锁定"):
        service.ask_advice({"batch": "b1"})


def test_probe_degrades_quietly_and_archives_when_available(tmp_path, monkeypatch):
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())
    _add_results(service)

    (service.root / "config.toml").unlink()
    quiet = service.ask_probe({"batch": "b1", "run": "model=large"})
    assert quiet["ok"] is True and quiet["available"] is False

    monkeypatch.setattr(web, "probe", lambda root, batches, run: {"question": "两组的数据增强配置一样吗？"})
    result = service.ask_probe({"batch": "b1", "run": "model=large"})

    assert result["probe"]["question"] == "两组的数据增强配置一样吗？"
    notes = [e for e in service._load()[0] if e.type == "note"]
    assert [n.payload["kind"] for n in notes] == ["ai_probe"]
    assert service.state()["batches"][0]["runs"][1]["verdict"] == "SURPRISE"


def test_probe_only_makes_sense_for_a_surprise(tmp_path):
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())
    _add_results(service)

    with pytest.raises(GuiInputError, match="超出预期"):
        service.ask_probe({"batch": "b1", "run": "model=base"})


def test_state_exposes_archived_ai_notes(tmp_path, monkeypatch):
    """存过的判断要能再看到，否则刷新一次就没了。"""
    service = GuiService(tmp_path / "p")
    service.create_batch(_batch_payload())
    monkeypatch.setattr(web, "advise", lambda root, design, runs: _FAKE_ADVICE)
    service.ask_advice({"batch": "b1"})

    batch = service.state()["batches"][0]
    assert batch["advice"]["ranking"] == ["model=large", "model=base"]


# ---------- 校准记录 ----------

def _judged_batch(service, rows):
    """建一个批次并录入结果。rows: [(run, 预测, 置信度, 实测)]"""
    payload = _batch_payload()
    payload["dimensions"] = [{"name": "model", "values": [r[0] for r in rows]}]
    payload["predictions"] = [
        {
            "run": f"model={run}",
            "metrics": {"top1_acc": predicted},
            "confidence": confidence,
            "rationale": "理由",
        }
        for run, predicted, confidence, _ in rows
    ]
    created = service.create_batch(payload)
    service.add_results(
        {
            "batch": created["batch"],
            "rows": [
                {"run": f"model={run}", "seed": 0, "metrics": {"top1_acc": actual}}
                for run, _, _, actual in rows
            ],
        }
    )
    return created["batch"]


def test_calibration_counts_hits_and_signed_bias(tmp_path):
    """命中率之外还要给带符号偏差：一直高估和一直低估是两种不同的毛病。"""
    service = GuiService(tmp_path / "p")
    _judged_batch(
        service,
        [
            ("a", "0.800", "high", 0.801),   # 命中，+0.001
            ("b", "0.800", "high", 0.900),   # 意外，+0.100（低估了）
        ],
    )

    cal = service.state()["calibration"]

    assert cal["judged"] == 2
    assert cal["hit"] == 1
    assert cal["bias"] == pytest.approx(0.0505, abs=1e-4)


def test_calibration_breaks_down_by_stated_confidence(tmp_path):
    """最有价值的一问：你说「高」的时候，真的更准吗？

    如果 high 的命中率并不比 low 好，那这个置信度字段就是噪声。
    """
    service = GuiService(tmp_path / "p")
    _judged_batch(
        service,
        [
            ("a", "0.800", "high", 0.801),
            ("b", "0.800", "high", 0.802),
            ("c", "0.800", "low", 0.900),
        ],
    )

    levels = {row["level"]: row for row in service.state()["calibration"]["by_confidence"]}

    assert levels["high"]["judged"] == 2 and levels["high"]["hit"] == 2
    assert levels["low"]["judged"] == 1 and levels["low"]["hit"] == 0
    assert "medium" not in levels  # 一条都没有的档次不占位置


def test_calibration_ignores_runs_that_cannot_be_judged(tmp_path):
    """没有结果、噪声过大、预测缺席的 run 都不进校准——它们没有对错可言。"""
    service = GuiService(tmp_path / "p")
    _bare_batch(service)
    service.add_results(
        {"batch": "b1", "rows": [{"run": "model=base", "seed": 0, "metrics": {"top1_acc": 0.81}}]}
    )

    cal = service.state()["calibration"]

    assert cal["judged"] == 0
    assert cal["bias"] is None
    assert cal["by_confidence"] == []


def test_calibration_recent_deviations_are_newest_first(tmp_path):
    service = GuiService(tmp_path / "p")
    _judged_batch(service, [("a", "0.800", "high", 0.801)])
    _judged_batch(service, [("b", "0.700", "low", 0.900)])

    recent = service.state()["calibration"]["recent"]

    assert [row["batch"] for row in recent] == ["b2", "b1"]
    assert recent[0]["hot"] is True and recent[1]["hot"] is False


def test_saving_a_paper_section_does_not_create_a_batch_warning(tmp_path):
    service = GuiService(tmp_path / "p")
    draft = service.create_draft({"title": "校准论文"})["draft"]

    service.save_section(
        {"draft": draft, "section": "discussion", "text": "正文", "materials": []}
    )

    assert service.state()["warnings"] == []


# ---------- 领域调研 ----------
#
# 与 AI 层同构：抓不到就降级，不报错不阻断。测试全部替换掉碰网络的那两个
# 函数——网络收窄在 openalex.fetch_json 一处，这里不该碰它。

from ari.openalex import Budget, OpenAlexUnavailable, Paper  # noqa: E402

_BUDGET = Budget(limit=1000, remaining=980, reset_seconds=71829)


def _paper(work, refs=(), year=2024, cited=10, title=None):
    return Paper(
        work=work,
        title=title or f"论文 {work}",
        year=year,
        authors=["某人"],
        venue="某会议",
        cited_by=cited,
        abstract=f"{work} 的摘要",
        referenced=list(refs),
    )


def _fake_openalex(monkeypatch, seed, milestones):
    monkeypatch.setattr(web, "openalex_search", lambda *a, **k: (seed, _BUDGET))
    monkeypatch.setattr(web, "fetch_by_ids", lambda works, **k: (milestones, _BUDGET))


def _survey(service, monkeypatch, **overrides):
    """开一个调研并抓一次。种子集 4 篇全都引用 FOUNDATION。"""
    payload = {"topic": "小数据集上的正则化", "query": "dropout small data", "from_year": 2022}
    payload.update(overrides)
    created = service.create_survey(payload)
    seed = [_paper(f"S{i}", refs=["FOUNDATION", f"X{i}"]) for i in range(4)]
    _fake_openalex(monkeypatch, seed, [_paper("FOUNDATION", year=2014, cited=34236,
                                              title="Dropout: a simple way…")])
    service.run_survey({"survey": created["survey"]})
    return created["survey"]


def test_survey_opens_and_records_the_query(tmp_path):
    """检索式存档：半年后你想知道当初到底搜了什么，答案得在账本里。"""
    service = GuiService(tmp_path / "p")

    created = service.create_survey({"topic": "小数据集上的正则化", "query": "dropout small data"})

    assert created == {"ok": True, "survey": "s1"}
    survey = service.state()["surveys"][0]
    assert survey["query"] == "dropout small data"
    assert survey["topic"] == "小数据集上的正则化"


def test_running_a_survey_tiers_by_citation_graph(tmp_path, monkeypatch):
    """里程碑是算出来的：4 篇种子全引了 FOUNDATION，阈值 3，它过线。"""
    service = GuiService(tmp_path / "p")
    _survey(service, monkeypatch)

    survey = service.state()["surveys"][0]
    milestones = {p["work"]: p for p in survey["milestones"]}
    assert list(milestones) == ["FOUNDATION"]
    assert milestones["FOUNDATION"]["in_set"] == 4
    assert len(survey["followups"]) == 4


def test_running_a_survey_twice_does_not_duplicate_papers(tmp_path, monkeypatch):
    """再抓一次是「补充」，不是「重来」。"""
    service = GuiService(tmp_path / "p")
    sid = _survey(service, monkeypatch)
    before = len([e for e in service._load()[0] if e.type == "paper_found"])

    service.run_survey({"survey": sid})

    assert len([e for e in service._load()[0] if e.type == "paper_found"]) == before


def test_survey_degrades_quietly_when_openalex_is_unreachable(tmp_path, monkeypatch):
    """断网不报错、不阻断——与 LLM 层同一条约定。"""
    service = GuiService(tmp_path / "p")
    created = service.create_survey({"topic": "x", "query": "y"})

    def refuse(*a, **k):
        raise OpenAlexUnavailable("连不上 OpenAlex：Network is unreachable")

    monkeypatch.setattr(web, "openalex_search", refuse)
    result = service.run_survey({"survey": created["survey"]})

    assert result["ok"] is True and result["available"] is False
    assert "连不上" in result["reason"]
    assert not [e for e in service._load()[0] if e.type == "paper_found"]


def test_reading_a_paper_requires_writing_down_what_you_took(tmp_path, monkeypatch):
    """和预测必填理由是同一个道理：不写下来，等于没读。"""
    service = GuiService(tmp_path / "p")
    sid = _survey(service, monkeypatch)

    with pytest.raises(GuiInputError, match="收获"):
        service.read_paper({"survey": sid, "work": "FOUNDATION", "takeaway": "  "})

    service.read_paper({"survey": sid, "work": "FOUNDATION", "takeaway": "模型平均，不是噪声注入"})
    survey = service.state()["surveys"][0]
    assert survey["milestones"][0]["read"] is True
    assert survey["milestones"][0]["takeaway"] == "模型平均，不是噪声注入"


def test_paper_can_be_retiered_by_hand(tmp_path, monkeypatch):
    service = GuiService(tmp_path / "p")
    sid = _survey(service, monkeypatch)

    service.retier_paper({"survey": sid, "work": "S0", "tier": "milestone"})

    survey = service.state()["surveys"][0]
    assert {p["work"] for p in survey["milestones"]} == {"FOUNDATION", "S0"}


def test_bottleneck_must_be_written_before_asking_ai(tmp_path, monkeypatch):
    """与预测层同一条锚定规则：先看 AI 的判断，你的分析就失去独立性了。"""
    service = GuiService(tmp_path / "p")
    sid = _survey(service, monkeypatch)

    monkeypatch.setattr(web, "reason_bottleneck", lambda *a: pytest.fail("写之前不该调用"))
    with pytest.raises(GuiInputError, match="先写下"):
        service.ask_bottleneck({"survey": sid})


def test_bottleneck_becomes_an_idea(tmp_path, monkeypatch):
    """调研以一句瓶颈陈述结束，一键立为想法——管线因此是连的。"""
    service = GuiService(tmp_path / "p")
    sid = _survey(service, monkeypatch)
    service.set_bottleneck({"survey": sid, "text": "没人分开量过容量与正则各自的贡献"})

    created = service.survey_to_idea({"survey": sid})

    idea = next(i for i in service.state()["ideas"] if i["id"] == created["idea"])
    assert idea["text"] == "没人分开量过容量与正则各自的贡献"
    assert idea["survey"] == sid


def test_survey_cannot_close_without_a_bottleneck(tmp_path, monkeypatch):
    """不落到那句话上，前面读的全白读。"""
    service = GuiService(tmp_path / "p")
    sid = _survey(service, monkeypatch)

    with pytest.raises(GuiInputError, match="瓶颈"):
        service.close_survey({"survey": sid})

    service.set_bottleneck({"survey": sid, "text": "卡在没有可控的容量-正则解耦实验"})
    service.close_survey({"survey": sid})
    assert service.state()["surveys"][0]["closed"] is True


def test_today_surfaces_unread_milestones(tmp_path, monkeypatch):
    """首屏要说「该精读什么」，否则调研页开了也没人回去。"""
    service = GuiService(tmp_path / "p")
    _survey(service, monkeypatch)

    kinds = {row["kind"] for row in service.state()["survey_todos"]}
    assert "待精读" in kinds


def test_a_draft_section_can_cite_a_survey(tmp_path, monkeypatch):
    """related work 的原始材料就是调研——里程碑清单加你的精读笔记。"""
    service = GuiService(tmp_path / "p")
    sid = _survey(service, monkeypatch)
    service.create_draft({"title": "容量与正则的解耦", "venue": "内部报告"})

    service.save_section(
        {
            "draft": "p1",
            "section": "related",
            "text": "见调研。",
            "materials": [{"survey": sid}],
        }
    )

    draft = service.state()["drafts"][0]
    section = next(s for s in draft["sections"] if s["name"] == "related")
    assert section["materials"] == [{"survey": "s1"}]


def test_citing_an_unknown_survey_is_refused(tmp_path):
    service = GuiService(tmp_path / "p")
    service.create_draft({"title": "x"})

    with pytest.raises(GuiInputError, match="不存在的调研"):
        service.save_section(
            {"draft": "p1", "section": "related", "text": "", "materials": [{"survey": "s9"}]}
        )
