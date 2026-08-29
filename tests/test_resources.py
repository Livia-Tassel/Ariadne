from __future__ import annotations

import sys

from ari.resources import asset_file


def test_source_assets_are_available():
    assert "Ariadne" in asset_file("webui", "index.html").read_text(encoding="utf-8")
    assert "从一个研究目录开始" in asset_file("desktopui", "index.html").read_text(
        encoding="utf-8"
    )


def test_frozen_bundle_assets_take_priority(tmp_path, monkeypatch):
    executable = tmp_path / "Ariadne.app" / "Contents" / "MacOS" / "Ariadne"
    executable.parent.mkdir(parents=True)
    executable.touch()
    resource = tmp_path / "Ariadne.app" / "Contents" / "Resources" / "webui" / "index.html"
    resource.parent.mkdir(parents=True)
    resource.write_text("bundled", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(executable))

    assert asset_file("webui", "index.html").read_text(encoding="utf-8") == "bundled"


def test_nested_asset_paths_resolve(tmp_path, monkeypatch):
    """前端拆成 lib/ views/ parts/ 之后，资源名会带 `/`。"""
    executable = tmp_path / "Ariadne.app" / "Contents" / "MacOS" / "Ariadne"
    executable.parent.mkdir(parents=True)
    executable.touch()
    resource = (
        tmp_path / "Ariadne.app" / "Contents" / "Resources" / "webui" / "lib" / "dom.js"
    )
    resource.parent.mkdir(parents=True)
    resource.write_text("export const $ = 1;", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(executable))

    assert "export const $" in asset_file("webui", "lib/dom.js").read_text(encoding="utf-8")


def test_paper_materials_remain_structured_instead_of_being_injected_into_text():
    source = asset_file("webui", "views/draft.js").read_text(encoding="utf-8")

    assert "materialLabel(material)" in source
    assert 'class="refs"' in source
    assert "referenceText" not in source
    assert "插入选中素材" not in source
