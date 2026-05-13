"""Integration tests — validate the example scenarios documented in README.

These tests load actual example strategy files and simulate the full pipeline
(message → strategy.query → simulated DB rows → strategy.react → emoji) to
verify that documented behavior matches the implementation.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.commands import ReactCommand
from bot.loader import load_strategy
from bot.yaml_strategy import YamlStrategy

# --- Paths ---

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


# --- Constants ---

BOT_UUID = "bot-uuid-1234-5678"


# --- Helpers ---


def make_context(text, group=None, mentions=None):
    """Create a mock signalbot Context."""
    ctx = MagicMock()
    ctx.message = MagicMock()
    ctx.message.text = text
    ctx.message.group = group
    ctx.message.mentions = mentions or []
    ctx.message.source_uuid = "test-sender-uuid"
    ctx.react = AsyncMock()
    return ctx


def make_db(rows=None):
    """Create a mock GristClient."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=rows or [])
    return db


# =============================================================================
# Stock check scenario (OVERVIEW.md / README)
# =============================================================================


class TestStockCheckScenario:
    """
    From OVERVIEW.md:
      "stock Bandages"    → bot reacts ✅
      "stock Unobtanium"  → bot reacts 🚫
      "stock Widgets"     → bot reacts ❓ (not in database)

    From README:
      prefix: "stock "
      query Products table, select [in_stock], where name: "{input}"
      map: in_stock 1→✅, 0→🚫
      empty: ❓
    """

    @pytest.fixture()
    def strategy(self):
        return YamlStrategy(
            {
                "rules": [
                    {
                        "name": "stock_check",
                        "match": {"prefix": "stock "},
                        "query": {
                            "table": "Products",
                            "select": ["in_stock"],
                            "where": {"name": "{input}"},
                        },
                        "react": {
                            "map": {
                                "column": "in_stock",
                                "values": {"1": "\u2705", "0": "\U0001F6AB"},
                            },
                            "empty": "\u2753",
                        },
                    }
                ]
            }
        )

    def test_stock_bandages_in_stock(self, strategy):
        """'stock Bandages' with in_stock=1 → ✅"""
        sql, args = strategy.query("stock Bandages")
        assert sql == "SELECT in_stock FROM Products WHERE LOWER(name) = ?"
        assert args == ["bandages"]

        emoji = strategy.react("stock Bandages", [{"in_stock": 1}])
        assert emoji == "\u2705"  # ✅

    def test_stock_unobtanium_out_of_stock(self, strategy):
        """'stock Unobtanium' with in_stock=0 → 🚫"""
        sql, args = strategy.query("stock Unobtanium")
        assert args == ["unobtanium"]

        emoji = strategy.react("stock Unobtanium", [{"in_stock": 0}])
        assert emoji == "\U0001F6AB"  # 🚫

    def test_stock_widgets_not_found(self, strategy):
        """'stock Widgets' with no rows → ❓"""
        emoji = strategy.react("stock Widgets", [])
        assert emoji == "\u2753"  # ❓

    def test_unrelated_message_ignored(self, strategy):
        """Non-stock messages produce no query and no reaction."""
        sql, args = strategy.query("hello world")
        assert sql == ""
        assert args == []

        emoji = strategy.react("hello world", [])
        assert emoji is None

    async def test_full_pipeline_in_stock(self, strategy):
        """End-to-end: stock check with mocked DB returns ✅."""
        db = make_db(rows=[{"in_stock": 1}])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("stock Bandages")

        await cmd.handle(ctx)

        db.execute.assert_awaited_once_with(
            "SELECT in_stock FROM Products WHERE LOWER(name) = ?", ["bandages"]
        )
        ctx.react.assert_awaited_once_with("\u2705")

    async def test_full_pipeline_not_found(self, strategy):
        """End-to-end: stock check with empty DB returns ❓."""
        db = make_db(rows=[])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("stock Widgets")

        await cmd.handle(ctx)

        ctx.react.assert_awaited_once_with("\u2753")


# =============================================================================
# Order status scenario (examples/order_status.yaml)
# =============================================================================


class TestOrderStatusYaml:
    """
    From examples/order_status.yaml:
      "order 12345" → query Orders WHERE order_id = '12345'
      status=shipped    → 📦
      status=delivered  → ✅
      status=cancelled  → ❌
      status=<other>    → ⏳ (default)
      no rows           → ❓ (empty)
    """

    @pytest.fixture()
    def strategy(self):
        return load_strategy(str(EXAMPLES_DIR / "order_status.yaml"))

    def test_query_generation(self, strategy):
        sql, args = strategy.query("order 12345")
        assert sql == "SELECT status FROM Orders WHERE LOWER(order_id) = ?"
        assert args == ["12345"]

    def test_shipped(self, strategy):
        emoji = strategy.react("order 12345", [{"status": "shipped"}])
        assert emoji == "\U0001F4E6"  # 📦

    def test_delivered(self, strategy):
        emoji = strategy.react("order 12345", [{"status": "delivered"}])
        assert emoji == "\u2705"  # ✅

    def test_cancelled(self, strategy):
        emoji = strategy.react("order 12345", [{"status": "cancelled"}])
        assert emoji == "\u274C"  # ❌

    def test_default_status(self, strategy):
        emoji = strategy.react("order 12345", [{"status": "processing"}])
        assert emoji == "\u23F3"  # ⏳

    def test_empty_rows(self, strategy):
        emoji = strategy.react("order 12345", [])
        assert emoji == "\u2753"  # ❓

    def test_no_match(self, strategy):
        sql, args = strategy.query("hello")
        assert sql == ""
        assert args == []

    def test_case_insensitive_prefix(self, strategy):
        sql, args = strategy.query("ORDER ABC")
        assert args == ["abc"]

    async def test_full_pipeline_shipped(self, strategy):
        """End-to-end: order lookup returns 📦 for shipped."""
        db = make_db(rows=[{"status": "shipped"}])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("order X123")

        await cmd.handle(ctx)

        db.execute.assert_awaited_once()
        ctx.react.assert_awaited_once_with("\U0001F4E6")


# =============================================================================
# Order status scenario (examples/order_status.py)
# =============================================================================


class TestOrderStatusPython:
    """
    From examples/order_status.py:
      Same behavior as the YAML version but implemented in Python.
    """

    @pytest.fixture()
    def strategy(self):
        return load_strategy(str(EXAMPLES_DIR / "order_status.py"))

    def test_query_generation(self, strategy):
        sql, args = strategy.query("order 12345")
        assert sql == "SELECT status FROM Orders WHERE LOWER(order_id) = ?"
        assert args == ["12345"]

    def test_shipped(self, strategy):
        emoji = strategy.react("order 12345", [{"status": "shipped"}])
        assert emoji == "\U0001F4E6"  # 📦

    def test_delivered(self, strategy):
        emoji = strategy.react("order 12345", [{"status": "delivered"}])
        assert emoji == "\u2705"  # ✅

    def test_cancelled(self, strategy):
        emoji = strategy.react("order 12345", [{"status": "cancelled"}])
        assert emoji == "\u274C"  # ❌

    def test_default_status(self, strategy):
        emoji = strategy.react("order 12345", [{"status": "processing"}])
        assert emoji == "\u23F3"  # ⏳

    def test_empty_rows(self, strategy):
        emoji = strategy.react("order 12345", [])
        assert emoji == "\u2753"  # ❓

    def test_no_match(self, strategy):
        sql, args = strategy.query("hello")
        assert sql == ""
        assert args == []

    def test_case_insensitive(self, strategy):
        sql, args = strategy.query("Order ABC")
        assert args == ["abc"]

    async def test_full_pipeline_delivered(self, strategy):
        """End-to-end: Python strategy order lookup returns ✅ for delivered."""
        db = make_db(rows=[{"status": "delivered"}])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("order Z999")

        await cmd.handle(ctx)

        ctx.react.assert_awaited_once_with("\u2705")


# =============================================================================
# Keyword allowlist scenario (examples/keyword_allowlist.yaml)
# =============================================================================


class TestKeywordAllowlistYaml:
    """
    From examples/keyword_allowlist.yaml:
      Any message → query Allowlist WHERE word = "{message}"
      If row found → react with the emoji column value
      If no rows   → no reaction (None)

    Documented table:
      hello  → 👋
      thanks → ❤️
      help   → 🆘
    """

    @pytest.fixture()
    def strategy(self):
        return load_strategy(str(EXAMPLES_DIR / "keyword_allowlist.yaml"))

    def test_query_any_message(self, strategy):
        sql, args = strategy.query("hello")
        assert sql == "SELECT emoji FROM Allowlist WHERE LOWER(word) = ?"
        assert args == ["hello"]

    def test_query_lowercases_message(self, strategy):
        """The {message} variable is lowercased."""
        sql, args = strategy.query("HELLO")
        assert args == ["hello"]

    def test_react_with_found_emoji(self, strategy):
        emoji = strategy.react("hello", [{"emoji": "\U0001F44B"}])
        assert emoji == "\U0001F44B"  # 👋

    def test_react_help(self, strategy):
        emoji = strategy.react("help", [{"emoji": "\U0001F198"}])
        assert emoji == "\U0001F198"  # 🆘

    def test_react_no_rows(self, strategy):
        """Unknown word → no reaction."""
        emoji = strategy.react("unknown", [])
        assert emoji is None

    async def test_full_pipeline_found(self, strategy):
        """End-to-end: keyword found in DB → react with emoji from column."""
        db = make_db(rows=[{"emoji": "\U0001F44B"}])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("hello")

        await cmd.handle(ctx)

        db.execute.assert_awaited_once_with(
            "SELECT emoji FROM Allowlist WHERE LOWER(word) = ?", ["hello"]
        )
        ctx.react.assert_awaited_once_with("\U0001F44B")

    async def test_full_pipeline_not_found(self, strategy):
        """End-to-end: keyword not in DB → no reaction."""
        db = make_db(rows=[])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("unknown")

        await cmd.handle(ctx)

        ctx.react.assert_not_awaited()


# =============================================================================
# Multi-rule strategy (PLAN.md / README multi-rule example)
# =============================================================================


class TestMultiRuleStrategy:
    """
    From PLAN.md and README multi-rule example:
      Rule 1: exact "ping"       → 🏓 (static, no query)
      Rule 2: prefix "order "    → query Orders, map status → emoji
      Rule 3: any (fallback)     → query Allowlist, column emoji
    """

    @pytest.fixture()
    def strategy(self):
        return YamlStrategy(
            {
                "rules": [
                    {
                        "name": "greeting",
                        "match": {"exact": "ping"},
                        "react": {"emoji": "\U0001F3D3"},
                    },
                    {
                        "name": "order_lookup",
                        "match": {"prefix": "order "},
                        "query": {
                            "table": "Orders",
                            "select": ["status"],
                            "where": {"order_id": "{input}"},
                        },
                        "react": {
                            "map": {
                                "column": "status",
                                "values": {
                                    "shipped": "\U0001F4E6",
                                    "delivered": "\u2705",
                                },
                                "default": "\u23F3",
                            },
                            "empty": "\u2753",
                        },
                    },
                    {
                        "name": "fallback",
                        "match": {"any": True},
                        "query": {
                            "table": "Allowlist",
                            "select": ["emoji"],
                            "where": {"word": "{message}"},
                        },
                        "react": {"column": "emoji"},
                    },
                ]
            }
        )

    def test_ping_matches_first_rule(self, strategy):
        """'ping' matches the exact rule and returns 🏓 with no query."""
        sql, args = strategy.query("ping")
        assert sql == ""
        assert args == []

        emoji = strategy.react("ping", [])
        assert emoji == "\U0001F3D3"  # 🏓

    def test_order_matches_second_rule(self, strategy):
        """'order ABC' matches the prefix rule and queries Orders."""
        sql, args = strategy.query("order ABC")
        assert sql == "SELECT status FROM Orders WHERE LOWER(order_id) = ?"
        assert args == ["abc"]

        emoji = strategy.react("order ABC", [{"status": "shipped"}])
        assert emoji == "\U0001F4E6"  # 📦

    def test_other_message_falls_to_allowlist(self, strategy):
        """Unmatched messages fall through to the catch-all Allowlist rule."""
        sql, args = strategy.query("thanks")
        assert sql == "SELECT emoji FROM Allowlist WHERE LOWER(word) = ?"
        assert args == ["thanks"]

    def test_first_match_wins_over_fallback(self, strategy):
        """'ping' matches rule 1, not the catch-all rule 3."""
        emoji = strategy.react("ping", [])
        assert emoji == "\U0001F3D3"

    async def test_full_pipeline_ping(self, strategy):
        """End-to-end: ping → 🏓 without hitting the database."""
        db = make_db()
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("ping")

        await cmd.handle(ctx)

        db.execute.assert_not_awaited()
        ctx.react.assert_awaited_once_with("\U0001F3D3")

    async def test_full_pipeline_order(self, strategy):
        """End-to-end: order lookup queries DB and maps status → emoji."""
        db = make_db(rows=[{"status": "delivered"}])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("order Z1")

        await cmd.handle(ctx)

        db.execute.assert_awaited_once()
        ctx.react.assert_awaited_once_with("\u2705")

    async def test_full_pipeline_fallback(self, strategy):
        """End-to-end: fallback → Allowlist query → column emoji."""
        db = make_db(rows=[{"emoji": "\u2764\uFE0F"}])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("thanks")

        await cmd.handle(ctx)

        db.execute.assert_awaited_once()
        ctx.react.assert_awaited_once_with("\u2764\uFE0F")

    async def test_full_pipeline_fallback_no_match_in_db(self, strategy):
        """End-to-end: fallback → Allowlist empty → no reaction."""
        db = make_db(rows=[])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("random gibberish")

        await cmd.handle(ctx)

        db.execute.assert_awaited_once()
        ctx.react.assert_not_awaited()


# =============================================================================
# YAML and Python strategies produce consistent results
# =============================================================================


class TestYamlPythonConsistency:
    """Both strategy formats should produce identical results for the same inputs."""

    @pytest.fixture()
    def yaml_strategy(self):
        return load_strategy(str(EXAMPLES_DIR / "order_status.yaml"))

    @pytest.fixture()
    def python_strategy(self):
        return load_strategy(str(EXAMPLES_DIR / "order_status.py"))

    @pytest.mark.parametrize(
        "message,expected_args",
        [
            ("order ABC", ["abc"]),
            ("order 12345", ["12345"]),
            ("order hello world", ["hello world"]),
        ],
    )
    def test_query_consistency(
        self, yaml_strategy, python_strategy, message, expected_args
    ):
        """Both formats produce the same SQL and args."""
        yaml_sql, yaml_args = yaml_strategy.query(message)
        py_sql, py_args = python_strategy.query(message)

        assert yaml_sql == py_sql
        assert yaml_args == py_args

    @pytest.mark.parametrize(
        "status,expected_emoji",
        [
            ("shipped", "\U0001F4E6"),
            ("delivered", "\u2705"),
            ("cancelled", "\u274C"),
        ],
    )
    def test_react_consistency(
        self, yaml_strategy, python_strategy, status, expected_emoji
    ):
        """Both formats map status values to the same emoji."""
        rows = [{"status": status}]
        yaml_emoji = yaml_strategy.react("order X", rows)
        py_emoji = python_strategy.react("order X", rows)

        assert yaml_emoji == py_emoji == expected_emoji

    def test_empty_rows_consistency(self, yaml_strategy, python_strategy):
        """Both formats return ❓ for empty rows."""
        yaml_emoji = yaml_strategy.react("order X", [])
        py_emoji = python_strategy.react("order X", [])

        assert yaml_emoji == py_emoji == "\u2753"

    def test_no_match_consistency(self, yaml_strategy, python_strategy):
        """Both formats return empty query for non-matching messages."""
        yaml_sql, _ = yaml_strategy.query("hello")
        py_sql, _ = python_strategy.query("hello")

        assert yaml_sql == py_sql == ""


# =============================================================================
# Error handling in the full pipeline
# =============================================================================


class TestPipelineErrorHandling:
    """Validate that the pipeline handles errors gracefully as documented."""

    async def test_db_error_suppresses_reaction(self):
        """Grist query failure → no reaction, no crash."""
        strategy = YamlStrategy(
            {
                "rules": [
                    {
                        "name": "test",
                        "match": {"prefix": "stock "},
                        "query": {
                            "table": "Products",
                            "select": ["in_stock"],
                            "where": {"name": "{input}"},
                        },
                        "react": {
                            "map": {
                                "column": "in_stock",
                                "values": {"1": "\u2705"},
                            },
                            "empty": "\u2753",
                        },
                    }
                ]
            }
        )
        db = make_db()
        db.execute = AsyncMock(side_effect=Exception("connection refused"))
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("stock Bandages")

        # Should not raise
        await cmd.handle(ctx)
        ctx.react.assert_not_awaited()

    async def test_empty_message_skips(self):
        """Empty messages are ignored — no query, no reaction."""
        strategy = YamlStrategy(
            {
                "rules": [
                    {
                        "name": "test",
                        "match": {"any": True},
                        "react": {"emoji": "\U0001F44B"},
                    }
                ]
            }
        )
        db = make_db()
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("")

        await cmd.handle(ctx)
        ctx.react.assert_not_awaited()

    async def test_none_message_skips(self):
        """None messages are ignored."""
        strategy = YamlStrategy(
            {
                "rules": [
                    {
                        "name": "test",
                        "match": {"any": True},
                        "react": {"emoji": "\U0001F44B"},
                    }
                ]
            }
        )
        db = make_db()
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context(None)

        await cmd.handle(ctx)
        ctx.react.assert_not_awaited()


# =============================================================================
# Expertise lookup scenario (README Python example)
# =============================================================================


class TestExpertiseLookupScenario:
    """
    From README:
      "can Alice help with python" → query Experts WHERE person=Alice AND topic=python
      rows found → 👍
      no rows    → 👎
    """

    @pytest.fixture()
    def strategy(self, tmp_path):
        f = tmp_path / "expertise.py"
        f.write_text(
            '''\
import re

class Strategy:
    PATTERN = re.compile(r"^can (\\w+) help with (\\w+)", re.IGNORECASE)

    def query(self, message_text: str) -> tuple[str, list]:
        m = self.PATTERN.search(message_text.strip())
        if not m:
            return ("", [])
        person, topic = m.group(1), m.group(2)
        return (
            "SELECT person FROM Experts WHERE person = ? AND topic = ?",
            [person, topic],
        )

    def react(self, message_text: str, rows: list[dict]) -> str | None:
        if rows:
            return "\\U0001F44D"
        return "\\U0001F44E"
'''
        )
        return load_strategy(str(f))

    def test_query_extraction(self, strategy):
        sql, args = strategy.query("can Alice help with python")
        assert sql == "SELECT person FROM Experts WHERE person = ? AND topic = ?"
        assert args == ["Alice", "python"]

    def test_react_found(self, strategy):
        emoji = strategy.react(
            "can Alice help with python", [{"person": "Alice"}]
        )
        assert emoji == "\U0001F44D"  # 👍

    def test_react_not_found(self, strategy):
        emoji = strategy.react("can Bob help with rust", [])
        assert emoji == "\U0001F44E"  # 👎

    def test_no_match(self, strategy):
        sql, args = strategy.query("hello world")
        assert sql == ""
        assert args == []

    async def test_full_pipeline_found(self, strategy):
        """End-to-end: expertise found → 👍."""
        db = make_db(rows=[{"person": "Alice"}])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("can Alice help with python")

        await cmd.handle(ctx)

        db.execute.assert_awaited_once_with(
            "SELECT person FROM Experts WHERE person = ? AND topic = ?",
            ["Alice", "python"],
        )
        ctx.react.assert_awaited_once_with("\U0001F44D")

    async def test_full_pipeline_not_found(self, strategy):
        """End-to-end: expertise not found → 👎."""
        db = make_db(rows=[])
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("can Bob help with rust")

        await cmd.handle(ctx)

        ctx.react.assert_awaited_once_with("\U0001F44E")
