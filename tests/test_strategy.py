"""Tests for the strategy loader."""

import pytest

from bot.loader import load_strategy


class TestLoadYamlStrategy:
    def test_loads_yaml(self, tmp_path):
        f = tmp_path / "strategy.yaml"
        f.write_text(
            """
rules:
  - name: test
    match:
      exact: "ping"
    react:
      emoji: "🏓"
"""
        )
        s = load_strategy(str(f))
        assert hasattr(s, "query")
        assert hasattr(s, "react")
        assert s.react("ping", []) == "🏓"

    def test_loads_yml(self, tmp_path):
        f = tmp_path / "strategy.yml"
        f.write_text(
            """
rules:
  - name: test
    match:
      exact: "hi"
    react:
      emoji: "👋"
"""
        )
        s = load_strategy(str(f))
        assert s.react("hi", []) == "👋"


class TestLoadPythonStrategy:
    def test_loads_python_class(self, tmp_path):
        f = tmp_path / "strategy.py"
        f.write_text(
            """
class Strategy:
    def query(self, message_text):
        return ("", [])
    def react(self, message_text, rows):
        return "👍"
"""
        )
        s = load_strategy(str(f))
        assert s.react("hello", []) == "👍"

    def test_raises_if_no_strategy_class(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("x = 1\n")
        with pytest.raises(RuntimeError, match="No Strategy class"):
            load_strategy(str(f))


class TestUnsupportedFormat:
    def test_raises_for_unknown_extension(self, tmp_path):
        f = tmp_path / "strategy.json"
        f.write_text("{}")
        with pytest.raises(RuntimeError, match="Unsupported strategy"):
            load_strategy(str(f))
