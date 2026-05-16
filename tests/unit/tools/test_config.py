"""Tests for tools/config.py — load_kgflow_config()."""

from pathlib import Path
from tools.config import load_kgflow_config


def test_load_existing_config(tmp_path):
    """TOML 文件存在且有效时返回解析后的 dict。"""
    config_content = '[project]\nlanguages = ["python"]\ntarget = "/some/path"\n'
    config_file = tmp_path / "kgflow.toml"
    config_file.write_text(config_content, encoding="utf-8")
    result = load_kgflow_config(tmp_path)
    assert result == {"project": {"languages": ["python"], "target": "/some/path"}}


def test_load_missing_config(tmp_path):
    """TOML 文件不存在时返回 None。"""
    result = load_kgflow_config(tmp_path)
    assert result is None


def test_load_empty_config(tmp_path):
    """空的 TOML 文件返回空 dict。"""
    config_file = tmp_path / "kgflow.toml"
    config_file.write_text("", encoding="utf-8")
    result = load_kgflow_config(tmp_path)
    assert result == {}


def test_load_config_with_languages(tmp_path):
    """验证 languages 字段正确解析。"""
    config_content = '[project]\nlanguages = ["python", "javascript"]\n'
    config_file = tmp_path / "kgflow.toml"
    config_file.write_text(config_content, encoding="utf-8")
    result = load_kgflow_config(tmp_path)
    assert result["project"]["languages"] == ["python", "javascript"]
