"""Tests for extractors/__init__.py — register, detect_language, create_extractor."""

from pathlib import Path
from extractors import register, detect_language, create_extractor, EXTRACTORS


def _create_file(dir_path: Path, rel_path: str):
    """Create a file under dir_path, creating parent dirs as needed."""
    file_path = dir_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("")
    return file_path


# ── register ──────────────────────────────────────────────────────────


def test_register_decorator():
    """@register 将类注册到 EXTRACTORS 字典。"""
    class FakeExtractor:  # noqa: E306
        pass

    # 清理可能已有的 testlang 注册
    was_present = "testlang" in EXTRACTORS
    old = EXTRACTORS.pop("testlang", None)

    decorated = register("testlang")(FakeExtractor)
    assert decorated is FakeExtractor
    assert EXTRACTORS.get("testlang") is FakeExtractor

    # 清理
    del EXTRACTORS["testlang"]
    if was_present and old:
        EXTRACTORS["testlang"] = old


# ── detect_language ───────────────────────────────────────────────────


def test_detect_language_python_by_files(tmp_path):
    _create_file(tmp_path, "module.py")
    assert detect_language(tmp_path) == "python"


def test_detect_language_javascript_by_files(tmp_path):
    _create_file(tmp_path, "app.js")
    assert detect_language(tmp_path) == "javascript"


def test_detect_language_go_by_files(tmp_path):
    _create_file(tmp_path, "main.go")
    assert detect_language(tmp_path) == "go"


def test_detect_language_mixed_most_prevalent(tmp_path):
    _create_file(tmp_path, "a.py")
    _create_file(tmp_path, "b.py")
    _create_file(tmp_path, "c.py")
    _create_file(tmp_path, "d.js")
    assert detect_language(tmp_path) == "python"


def test_detect_language_no_files_fallback(tmp_path):
    """无识别文件时默认返回 python。"""
    _create_file(tmp_path, "readme.md")
    assert detect_language(tmp_path) == "python"


def test_detect_language_config_override(tmp_path):
    """配置的 languages 应该覆盖文件后缀检测。"""
    _create_file(tmp_path, "app.js")
    config = {"project": {"languages": ["python"]}}
    assert detect_language(tmp_path, kgflow_config=config) == "python"


def test_detect_language_respects_excluded_dirs(tmp_path):
    """排除目录内的文件不应参与语言检测。"""
    _create_file(tmp_path, ".venv/lib/site-packages/pkg.py")
    _create_file(tmp_path, "__pycache__/foo.py")
    _create_file(tmp_path, "a.js")
    _create_file(tmp_path, "b.js")
    _create_file(tmp_path, "c.js")
    assert detect_language(tmp_path) == "javascript"


# ── create_extractor ─────────────────────────────────────────────────


def test_create_extractor_python(tmp_path):
    """create_extractor('python') 返回 PythonAstExtractor 实例。"""
    extractor = create_extractor("python", tmp_path)
    from extractors.python_extractor import PythonAstExtractor
    assert isinstance(extractor, PythonAstExtractor)
    assert extractor.language == "python"


def test_create_extractor_unknown_language(tmp_path):
    """未知语言应抛出 ValueError。"""
    import pytest
    with pytest.raises(ValueError, match="No extractor registered"):
        create_extractor("rust", tmp_path)
