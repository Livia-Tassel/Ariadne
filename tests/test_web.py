"""v0.2 GUI 的应用服务与本地 HTTP 入口。"""

from __future__ import annotations

import json
import threading
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
        assert "新实验" in html

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
