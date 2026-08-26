"""Ariadne 桌面应用壳。

pywebview 只负责原生窗口、系统目录选择器和 WebKit 容器；业务数据仍由
``GuiService`` / ``runs.jsonl`` 管理。这个边界让浏览器版、桌面版与 CLI
共享同一套领域规则。
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Callable

from .web import make_server
from .workspace import initialize_project


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def application_data_dir() -> Path:
    """返回符合当前操作系统习惯的应用数据目录。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Ariadne"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / "Ariadne"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ariadne"


class RecentProjects:
    """最近项目列表。它只是启动便利信息，不参与实验数据投影。"""

    def __init__(self, path: str | Path | None = None, limit: int = 6):
        self.path = Path(path) if path else application_data_dir() / "recent-projects.json"
        self.limit = limit

    def list(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        rows = data.get("projects") if isinstance(data, dict) else []
        if not isinstance(rows, list):
            return []
        result = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = row.get("path")
            if not isinstance(raw, str):
                continue
            path = Path(raw).expanduser()
            key = str(path)
            if key in seen or not path.is_dir() or not (path / "runs.jsonl").exists():
                continue
            seen.add(key)
            result.append(
                {
                    "path": key,
                    "name": path.name or key,
                    "last_opened": row.get("last_opened") or "",
                }
            )
        return result[: self.limit]

    def touch(self, project_dir: str | Path) -> None:
        path = Path(project_dir).expanduser().resolve()
        rows = [row for row in self.list() if row["path"] != str(path)]
        rows.insert(0, {"path": str(path), "name": path.name, "last_opened": _now()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"v": 1, "projects": rows[: self.limit]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def launcher_html() -> str:
    """把启动页三件静态资源组装成可直接交给原生 WebView 的 HTML。"""
    root = files("ari").joinpath("desktopui")
    html = root.joinpath("index.html").read_text(encoding="utf-8")
    css = root.joinpath("styles.css").read_text(encoding="utf-8")
    javascript = root.joinpath("app.js").read_text(encoding="utf-8")
    return html.replace("/*__ARIADNE_CSS__*/", css).replace("/*__ARIADNE_JS__*/", javascript)


class DesktopBridge:
    """启动页与原生窗口之间的窄桥。"""

    def __init__(
        self,
        *,
        recent: RecentProjects | None = None,
        server_factory: Callable = make_server,
        webview_module=None,
    ):
        self.recent = recent or RecentProjects()
        self.server_factory = server_factory
        self.webview_module = webview_module
        self.window = None
        self.server = None
        self.server_thread = None
        self.current_project: Path | None = None

    def bind(self, window) -> None:
        self.window = window

    def bootstrap(self) -> dict:
        return {"ok": True, "recent_projects": self.recent.list()}

    def choose_project(self) -> dict:
        if self.window is None:
            return {"ok": False, "error": "应用窗口还没有准备好"}
        webview = self._webview()
        initial = self._initial_directory()
        selected = self.window.create_file_dialog(
            webview.FileDialog.FOLDER,
            directory=str(initial),
            allow_multiple=False,
        )
        if not selected:
            return {"ok": False, "cancelled": True}
        path = Path(selected[0] if isinstance(selected, (list, tuple)) else selected)
        if not path.is_dir():
            return {"ok": False, "error": "选择的目录不存在"}

        if not (path / "runs.jsonl").exists() and any(path.iterdir()):
            confirmed = self.window.create_confirmation_dialog(
                "在这个目录创建 Ariadne 项目？",
                f"Ariadne 会在“{path.name}”中新增 runs.jsonl、config.toml 和 logs 文件夹，"
                "不会修改已有文件。",
            )
            if not confirmed:
                return {"ok": False, "cancelled": True}
        return self._open_project(path)

    def open_recent(self, path: str) -> dict:
        project = Path(path).expanduser()
        if not project.is_dir() or not (project / "runs.jsonl").exists():
            return {"ok": False, "error": "这个最近项目已经被移动，或不是 Ariadne 项目"}
        return self._open_project(project)

    def show_launcher(self) -> dict:
        if self.window is None:
            return {"ok": False, "error": "应用窗口还没有准备好"}
        old_server = self.server
        self.server = None
        self.server_thread = None
        self.current_project = None
        self.window.title = "Ariadne"
        self.window.load_html(launcher_html())
        if old_server is not None:
            threading.Thread(target=self._stop_server, args=(old_server,), daemon=True).start()
        return {"ok": True}

    def shutdown(self) -> None:
        if self.server is not None:
            self._stop_server(self.server)
            self.server = None

    def _open_project(self, project_dir: Path) -> dict:
        if self.window is None:
            return {"ok": False, "error": "应用窗口还没有准备好"}
        root = initialize_project(project_dir, exist_ok=True)
        try:
            new_server = self.server_factory(root, host="127.0.0.1", port=0)
        except OSError as exc:
            return {"ok": False, "error": f"无法启动本地工作台：{exc}"}

        thread = threading.Thread(target=new_server.serve_forever, daemon=True)
        thread.start()
        port = new_server.server_address[1]
        old_server = self.server
        self.server = new_server
        self.server_thread = thread
        self.current_project = root
        self.recent.touch(root)
        self.window.title = f"Ariadne · {root.name}"
        self.window.load_url(f"http://127.0.0.1:{port}/")
        if old_server is not None:
            threading.Thread(target=self._stop_server, args=(old_server,), daemon=True).start()
        return {"ok": True, "path": str(root), "name": root.name}

    def _initial_directory(self) -> Path:
        if self.current_project is not None:
            return self.current_project.parent
        recent = self.recent.list()
        if recent:
            return Path(recent[0]["path"]).parent
        documents = Path.home() / "Documents"
        return documents if documents.is_dir() else Path.home()

    def _webview(self):
        if self.webview_module is not None:
            return self.webview_module
        import webview

        return webview

    @staticmethod
    def _stop_server(server) -> None:
        try:
            server.shutdown()
        finally:
            server.server_close()


def main() -> None:
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "桌面组件尚未安装。开发环境请运行：uv sync --extra desktop"
        ) from exc

    bridge = DesktopBridge(webview_module=webview)
    window = webview.create_window(
        "Ariadne",
        html=launcher_html(),
        js_api=bridge,
        width=1280,
        height=820,
        min_size=(900, 640),
        background_color="#f4f2ed",
        text_select=True,
    )
    bridge.bind(window)
    window.events.closed += bridge.shutdown
    webview.settings["SHOW_DEFAULT_MENUS"] = True
    webview.start(debug=False, private_mode=True)


if __name__ == "__main__":
    main()
