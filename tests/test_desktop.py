"""桌面启动器：目录选择、最近项目与原生窗口切换。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ari.desktop import DesktopBridge, RecentProjects, launcher_html


class FakeFileDialog:
    FOLDER = "folder"


class FakeWebview:
    FileDialog = FakeFileDialog


class FakeWindow:
    def __init__(self, selected=None, confirmed=True):
        self.selected = selected
        self.confirmed = confirmed
        self.dialog_calls = []
        self.confirmation_calls = []
        self.urls = []
        self.html = []
        self.title = "Ariadne"

    def create_file_dialog(self, kind, **options):
        self.dialog_calls.append((kind, options))
        return self.selected

    def create_confirmation_dialog(self, title, message):
        self.confirmation_calls.append((title, message))
        return self.confirmed

    def load_url(self, url):
        self.urls.append(url)

    def load_html(self, html):
        self.html.append(html)


class FakeServer:
    def __init__(self, port=43123):
        self.server_address = ("127.0.0.1", port)
        self.shutdown_called = False
        self.closed = False

    def serve_forever(self):
        return

    def shutdown(self):
        self.shutdown_called = True

    def server_close(self):
        self.closed = True


def _bridge(tmp_path, window, servers=None):
    made = servers if servers is not None else []

    def factory(root, host, port):
        server = FakeServer(43123 + len(made))
        made.append((Path(root), host, port, server))
        return server

    bridge = DesktopBridge(
        recent=RecentProjects(tmp_path / "app-data" / "recent.json"),
        server_factory=factory,
        webview_module=FakeWebview,
    )
    bridge.bind(window)
    return bridge, made


def test_launcher_assets_are_embedded_and_need_no_external_files():
    html = launcher_html()

    assert "从一个研究目录开始" in html
    assert "window.pywebview.api.choose_project" in html
    assert "/*__ARIADNE_CSS__*/" not in html
    assert "/*__ARIADNE_JS__*/" not in html


def test_choosing_an_empty_folder_initializes_and_opens_it(tmp_path):
    project = tmp_path / "my-study"
    project.mkdir()
    window = FakeWindow(selected=(str(project),))
    bridge, made = _bridge(tmp_path, window)

    result = bridge.choose_project()

    assert result == {"ok": True, "path": str(project), "name": "my-study"}
    assert (project / "runs.jsonl").exists()
    assert (project / "config.toml").exists()
    assert (project / "logs").is_dir()
    assert made[0][:3] == (project, "127.0.0.1", 0)
    assert window.urls == ["http://127.0.0.1:43123/"]
    assert window.title == "Ariadne · my-study"
    assert bridge.bootstrap()["recent_projects"][0]["path"] == str(project)


def test_nonempty_folder_requires_confirmation_before_adding_project_files(tmp_path):
    project = tmp_path / "existing-work"
    project.mkdir()
    (project / "notes.txt").write_text("mine", encoding="utf-8")
    window = FakeWindow(selected=(str(project),), confirmed=False)
    bridge, made = _bridge(tmp_path, window)

    result = bridge.choose_project()

    assert result == {"ok": False, "cancelled": True}
    assert window.confirmation_calls
    assert not (project / "runs.jsonl").exists()
    assert made == []


def test_open_recent_rejects_a_plain_folder(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    bridge, _ = _bridge(tmp_path, FakeWindow())

    result = bridge.open_recent(str(folder))

    assert result["ok"] is False
    assert "不是 Ariadne 项目" in result["error"]


def test_recent_projects_are_deduplicated_and_missing_entries_are_pruned(tmp_path):
    storage = tmp_path / "recent.json"
    first = tmp_path / "one"
    second = tmp_path / "two"
    for project in (first, second):
        project.mkdir()
        (project / "runs.jsonl").touch()

    recent = RecentProjects(storage)
    recent.touch(first)
    recent.touch(second)
    recent.touch(first)
    rows = recent.list()

    assert [row["path"] for row in rows] == [str(first), str(second)]

    second.rename(tmp_path / "moved")
    assert [row["path"] for row in recent.list()] == [str(first)]


def test_corrupt_recent_file_is_ignored(tmp_path):
    storage = tmp_path / "recent.json"
    storage.write_text("{broken", encoding="utf-8")

    assert RecentProjects(storage).list() == []


def test_switching_projects_stops_the_previous_server(tmp_path):
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    window = FakeWindow()
    bridge, made = _bridge(tmp_path, window)

    bridge._open_project(first)
    old = made[0][3]
    bridge._open_project(second)
    for _ in range(20):
        if old.shutdown_called:
            break
        time.sleep(0.01)

    assert old.shutdown_called is True
    assert old.closed is True
    assert bridge.current_project == second


def test_returning_to_launcher_stops_project_server(tmp_path):
    project = tmp_path / "one"
    project.mkdir()
    window = FakeWindow()
    bridge, made = _bridge(tmp_path, window)
    bridge._open_project(project)
    server = made[0][3]

    result = bridge.show_launcher()
    for _ in range(20):
        if server.shutdown_called:
            break
        time.sleep(0.01)

    assert result == {"ok": True}
    assert window.title == "Ariadne"
    assert "从一个研究目录开始" in window.html[0]
    assert server.shutdown_called is True


def test_recent_file_has_a_small_versioned_shape(tmp_path):
    project = tmp_path / "one"
    project.mkdir()
    (project / "runs.jsonl").touch()
    storage = tmp_path / "recent.json"

    RecentProjects(storage).touch(project)
    saved = json.loads(storage.read_text(encoding="utf-8"))

    assert saved["v"] == 1
    assert saved["projects"][0]["path"] == str(project)
