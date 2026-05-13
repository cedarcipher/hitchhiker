"""Tests for the YAML strategy engine — match, query, and react logic."""

import pytest

from bot.yaml_strategy import YamlStrategy


# --- Helpers ---


def make_strategy(rules, tables=None):
    config = {"rules": rules}
    if tables:
        config["tables"] = tables
    return YamlStrategy(config)


# --- Match tests ---


class TestPrefixMatch:
    def test_matches_and_extracts_input(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "order "},
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("order 12345")
        assert sql == "SELECT x FROM T WHERE LOWER(id) = ?"
        assert args == ["12345"]

    def test_case_insensitive(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "Order "},
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("ORDER 999")
        assert args == ["999"]

    def test_strips_whitespace(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "order "},
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("  order 12345  ")
        assert args == ["12345"]

    def test_no_match(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "order "},
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("hello world")
        assert sql == ""
        assert args == []


class TestExactMatch:
    def test_matches(self):
        s = make_strategy(
            [{"name": "test", "match": {"exact": "ping"}, "react": {"emoji": "🏓"}}]
        )
        emoji = s.react("ping", [])
        assert emoji == "🏓"

    def test_case_insensitive(self):
        s = make_strategy(
            [{"name": "test", "match": {"exact": "ping"}, "react": {"emoji": "🏓"}}]
        )
        emoji = s.react("PING", [])
        assert emoji == "🏓"

    def test_strips_whitespace(self):
        s = make_strategy(
            [{"name": "test", "match": {"exact": "ping"}, "react": {"emoji": "🏓"}}]
        )
        assert s.react("  ping  ", []) == "🏓"

    def test_no_match(self):
        s = make_strategy(
            [{"name": "test", "match": {"exact": "ping"}, "react": {"emoji": "🏓"}}]
        )
        emoji = s.react("pong", [])
        assert emoji is None


class TestSuffixMatch:
    def test_matches_and_extracts_input(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"suffix": " please"},
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"q": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("help me please")
        assert args == ["help me"]

    def test_case_insensitive(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"suffix": " please"},
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"q": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("HELP ME PLEASE")
        assert args == ["help me"]

    def test_strips_whitespace(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"suffix": " please"},
                    "react": {"emoji": "✅"},
                }
            ]
        )
        assert s.react("  help me please  ", []) == "✅"


class TestContainsMatch:
    def test_matches(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"contains": "help"},
                    "react": {"emoji": "🆘"},
                }
            ]
        )
        emoji = s.react("can you help me", [])
        assert emoji == "🆘"

    def test_case_insensitive(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"contains": "help"},
                    "react": {"emoji": "🆘"},
                }
            ]
        )
        assert s.react("PLEASE HELP", []) == "🆘"

    def test_strips_whitespace(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"contains": "help"},
                    "react": {"emoji": "🆘"},
                }
            ]
        )
        assert s.react("  can you help me  ", []) == "🆘"

    def test_no_match(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"contains": "help"},
                    "react": {"emoji": "🆘"},
                }
            ]
        )
        emoji = s.react("hello", [])
        assert emoji is None


class TestRegexMatch:
    def test_with_capture_group(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"regex": r"^(\d{4,})$"},
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("12345")
        assert args == ["12345"]

    def test_case_insensitive(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"regex": r"^order ([a-z]+)$"},
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("ORDER ABC")
        assert args == ["abc"]

    def test_strips_capture_group(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"regex": r"^order\s+(.+)$"},
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("order  hello  ")
        assert args == ["hello"]

    def test_no_match(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"regex": r"^(\d{4,})$"},
                    "react": {"emoji": "✅"},
                }
            ]
        )
        emoji = s.react("abc", [])
        assert emoji is None


class TestAnyMatch:
    def test_matches_everything(self):
        s = make_strategy(
            [{"name": "test", "match": {"any": True}, "react": {"emoji": "👋"}}]
        )
        emoji = s.react("literally anything", [])
        assert emoji == "👋"


class TestAnyOfMatch:
    def test_matches_first_alternative(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "any_of": [
                            {"prefix": "stock "},
                            {"regex": r"^BAND-\d+$"},
                        ]
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        assert s.react("stock Bandages", []) == "✅"

    def test_matches_later_alternative(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "any_of": [
                            {"prefix": "stock "},
                            {"regex": r"^BAND-\d+$"},
                        ]
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        assert s.react("BAND-12345", []) == "✅"

    def test_no_alternative_matches(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "any_of": [
                            {"prefix": "stock "},
                            {"regex": r"^BAND-\d+$"},
                        ]
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        assert s.react("hello", []) is None

    def test_first_with_capture_wins(self):
        """A capturing alternative beats a non-capturing one that fired earlier."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "any_of": [
                            {"contains": "stock"},
                            {"regex": r"BAND-(\d+)"},
                        ]
                    },
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        _, args = s.query("stock BAND-12345")
        assert args == ["12345"]

    def test_fallback_when_no_capture(self):
        """When matchers match but none capture, the rule still fires."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "any_of": [
                            {"contains": "hello"},
                            {"contains": "world"},
                        ]
                    },
                    "react": {"emoji": "👋"},
                }
            ]
        )
        assert s.react("hello world", []) == "👋"

    def test_uses_first_alternative_capture(self):
        """First capturing alternative wins, even if a later one would also capture."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "any_of": [
                            {"prefix": "stock "},
                            {"regex": r"BAND-(\d+)"},
                        ]
                    },
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        _, args = s.query("stock BAND-12345")
        assert args == ["band-12345"]


class TestAllOfMatch:
    def test_all_match(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "all_of": [
                            {"prefix": "stock "},
                            {"regex": r"\d{4,}"},
                        ]
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        assert s.react("stock 12345", []) == "✅"

    def test_one_fails_no_match(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "all_of": [
                            {"prefix": "stock "},
                            {"regex": r"\d{4,}"},
                        ]
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        assert s.react("stock abc", []) is None
        assert s.react("inventory 12345", []) is None

    def test_last_capture_wins(self):
        """When multiple matchers capture, the last one's {input} is used."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "all_of": [
                            {"prefix": "order "},
                            {"regex": r"(\d+)"},
                        ]
                    },
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        _, args = s.query("order ABC-123 priority")
        assert args == ["123"]

    def test_mixed_capture_and_non_capture(self):
        """A capturing matcher's {input} survives through a non-capturing matcher."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "all_of": [
                            {"regex": r"order (\d+)"},
                            {"contains": "please"},
                        ]
                    },
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        _, args = s.query("order 42 please")
        assert args == ["42"]
        assert s.react("order 42", []) is None


class TestMatchValidation:
    def test_rejects_empty_any_of(self):
        with pytest.raises(ValueError, match="must contain at least one matcher"):
            make_strategy(
                [
                    {
                        "name": "test",
                        "match": {"any_of": []},
                        "react": {"emoji": "✅"},
                    }
                ]
            )

    def test_rejects_empty_all_of(self):
        with pytest.raises(ValueError, match="must contain at least one matcher"):
            make_strategy(
                [
                    {
                        "name": "test",
                        "match": {"all_of": []},
                        "react": {"emoji": "✅"},
                    }
                ]
            )

    def test_rejects_mixed_top_level_keys(self):
        with pytest.raises(ValueError, match="exactly one of"):
            make_strategy(
                [
                    {
                        "name": "test",
                        "match": {"any_of": [{"prefix": "x"}], "prefix": "y"},
                        "react": {"emoji": "✅"},
                    }
                ]
            )

    def test_rejects_empty_match(self):
        with pytest.raises(ValueError, match="exactly one of"):
            make_strategy(
                [
                    {
                        "name": "test",
                        "match": {},
                        "react": {"emoji": "✅"},
                    }
                ]
            )

    def test_rejects_invalid_child(self):
        """A malformed matcher inside any_of is caught recursively."""
        with pytest.raises(ValueError, match="exactly one of"):
            make_strategy(
                [
                    {
                        "name": "test",
                        "match": {"any_of": [{}]},
                        "react": {"emoji": "✅"},
                    }
                ]
            )

    def test_accepts_existing_single_key_forms(self):
        """All existing leaf matcher forms still load without error."""
        for leaf in [
            {"prefix": "x"},
            {"suffix": "x"},
            {"exact": "x"},
            {"contains": "x"},
            {"regex": "x"},
            {"any": True},
        ]:
            make_strategy(
                [{"name": "t", "match": leaf, "react": {"emoji": "✅"}}]
            )


class TestNestedMatchers:
    def test_any_of_containing_all_of(self):
        """An any_of branch can contain an all_of (and vice versa)."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {
                        "any_of": [
                            {
                                "all_of": [
                                    {"prefix": "stock "},
                                    {"regex": r"\d{4,}"},
                                ]
                            },
                            {"regex": r"^BAND-\d+$"},
                        ]
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        assert s.react("stock 12345", []) == "✅"
        assert s.react("BAND-99", []) == "✅"
        assert s.react("hello", []) is None
        assert s.react("stock abc", []) is None


# --- Query builder tests ---


class TestStructuredQuery:
    def test_basic(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "order "},
                    "query": {
                        "table": "Orders",
                        "select": ["status"],
                        "where": {"order_id": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("order ABC")
        assert sql == "SELECT status FROM Orders WHERE LOWER(order_id) = ?"
        assert args == ["abc"]

    def test_multiple_where_clauses(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "query": {
                        "table": "T",
                        "select": ["x"],
                        "where": {"a": "{message}", "b": "fixed"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("Hello")
        assert "LOWER(a) = ?" in sql
        assert "LOWER(b) = ?" in sql
        assert "hello" in args  # {message} is lowercased
        assert "fixed" in args

    def test_with_limit(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "query": {"table": "T", "select": ["x"], "limit": 5},
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, _ = s.query("anything")
        assert sql.endswith("LIMIT 5")

    def test_select_star_default(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "query": {"table": "T"},
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, _ = s.query("anything")
        assert sql.startswith("SELECT * FROM T")


class TestRawSqlQuery:
    def test_basic(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "find "},
                    "query": {
                        "sql": "SELECT x FROM T WHERE id = ? AND active = 1",
                        "args": ["{input}"],
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        sql, args = s.query("find 42")
        assert sql == "SELECT x FROM T WHERE id = ? AND active = 1"
        assert args == ["42"]


# --- React evaluator tests ---


class TestReactMap:
    def test_mapped_value(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "react": {
                        "map": {
                            "column": "status",
                            "values": {"shipped": "📦", "delivered": "✅"},
                            "default": "⏳",
                        },
                        "empty": "❓",
                    },
                }
            ]
        )
        assert s.react("x", [{"status": "shipped"}]) == "📦"
        assert s.react("x", [{"status": "delivered"}]) == "✅"

    def test_default_value(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "react": {
                        "map": {
                            "column": "status",
                            "values": {"shipped": "📦"},
                            "default": "⏳",
                        },
                    },
                }
            ]
        )
        assert s.react("x", [{"status": "unknown"}]) == "⏳"

    def test_empty_rows(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "react": {
                        "map": {"column": "s", "values": {}},
                        "empty": "❓",
                    },
                }
            ]
        )
        assert s.react("x", []) == "❓"

    def test_empty_null(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "react": {"map": {"column": "s", "values": {}}},
                }
            ]
        )
        assert s.react("x", []) is None

    def test_case_insensitive_lookup(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "react": {
                        "map": {
                            "column": "status",
                            "values": {"shipped": "📦", "delivered": "✅"},
                            "default": "⏳",
                        },
                    },
                }
            ]
        )
        # DB returns mixed case, YAML keys are lowercase
        assert s.react("x", [{"status": "Shipped"}]) == "📦"
        assert s.react("x", [{"status": "DELIVERED"}]) == "✅"
        assert s.react("x", [{"status": "shipped"}]) == "📦"

    def test_case_insensitive_yaml_keys(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "react": {
                        "map": {
                            "column": "status",
                            "values": {"Shipped": "📦", "PENDING": "⏳"},
                        },
                    },
                }
            ]
        )
        # DB returns lowercase, YAML keys are mixed case
        assert s.react("x", [{"status": "shipped"}]) == "📦"
        assert s.react("x", [{"status": "pending"}]) == "⏳"

    def test_integer_column_values(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "react": {
                        "map": {
                            "column": "in_stock",
                            "values": {"1": "✅", "0": "🚫"},
                        },
                        "empty": "❓",
                    },
                }
            ]
        )
        # Grist may return integers; map converts via str()
        assert s.react("x", [{"in_stock": 1}]) == "✅"
        assert s.react("x", [{"in_stock": 0}]) == "🚫"


class TestReactColumn:
    def test_uses_column_value_as_emoji(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "react": {"column": "emoji"},
                }
            ]
        )
        assert s.react("x", [{"emoji": "👋"}]) == "👋"

    def test_empty_rows(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "react": {"column": "emoji", "empty": "❓"},
                }
            ]
        )
        assert s.react("x", []) == "❓"


class TestReactStaticEmoji:
    def test_returns_static_emoji_with_rows(self):
        s = make_strategy(
            [{"name": "test", "match": {"exact": "ping"}, "react": {"emoji": "🏓"}}]
        )
        assert s.react("ping", [{"x": 1}]) == "🏓"

    def test_returns_static_emoji_no_rows_no_empty(self):
        s = make_strategy(
            [{"name": "test", "match": {"exact": "ping"}, "react": {"emoji": "🏓"}}]
        )
        # No empty handler → emoji fires unconditionally (e.g. no-query rules)
        assert s.react("ping", []) == "🏓"

    def test_existence_check_found(self):
        """emoji + empty: react with emoji when row exists."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "check "},
                    "query": {
                        "table": "T",
                        "select": ["name"],
                        "where": {"name": "{input}"},
                    },
                    "react": {"emoji": "✅", "empty": "❓"},
                }
            ]
        )
        assert s.react("check foo", [{"name": "foo"}]) == "✅"

    def test_existence_check_not_found(self):
        """emoji + empty: react with empty when no rows."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "check "},
                    "query": {
                        "table": "T",
                        "select": ["name"],
                        "where": {"name": "{input}"},
                    },
                    "react": {"emoji": "✅", "empty": "❓"},
                }
            ]
        )
        assert s.react("check bar", []) == "❓"


class TestNoQueryRule:
    def test_query_returns_empty(self):
        s = make_strategy(
            [{"name": "test", "match": {"exact": "ping"}, "react": {"emoji": "🏓"}}]
        )
        sql, args = s.query("ping")
        assert sql == ""
        assert args == []

    def test_react_still_works(self):
        s = make_strategy(
            [{"name": "test", "match": {"exact": "ping"}, "react": {"emoji": "🏓"}}]
        )
        emoji = s.react("ping", [])
        assert emoji == "🏓"


class TestMultiRuleFirstMatchWins:
    def test_first_rule_wins(self):
        s = make_strategy(
            [
                {
                    "name": "specific",
                    "match": {"exact": "ping"},
                    "react": {"emoji": "🏓"},
                },
                {
                    "name": "fallback",
                    "match": {"any": True},
                    "react": {"emoji": "❌"},
                },
            ]
        )
        assert s.react("ping", []) == "🏓"

    def test_falls_through_to_second(self):
        s = make_strategy(
            [
                {
                    "name": "specific",
                    "match": {"exact": "ping"},
                    "react": {"emoji": "🏓"},
                },
                {
                    "name": "fallback",
                    "match": {"any": True},
                    "react": {"emoji": "❌"},
                },
            ]
        )
        assert s.react("something else", []) == "❌"


# --- Respond tests ---


class TestRespondStatic:
    def test_static_text_default_quote_true(self):
        s = make_strategy(
            [
                {
                    "name": "welcome",
                    "match": {"exact": "hi"},
                    "respond": {"text": "Welcome!"},
                }
            ]
        )
        assert s.respond("hi", []) == ("Welcome!", True)

    def test_explicit_quote_false(self):
        s = make_strategy(
            [
                {
                    "name": "welcome",
                    "match": {"exact": "hi"},
                    "respond": {"text": "Welcome!", "quote": False},
                }
            ]
        )
        assert s.respond("hi", []) == ("Welcome!", False)

    def test_no_respond_block_returns_none(self):
        s = make_strategy(
            [
                {
                    "name": "welcome",
                    "match": {"exact": "hi"},
                    "react": {"emoji": "👋"},
                }
            ]
        )
        assert s.respond("hi", []) is None

    def test_no_rule_matches_returns_none(self):
        s = make_strategy(
            [
                {
                    "name": "welcome",
                    "match": {"exact": "hi"},
                    "respond": {"text": "Welcome!"},
                }
            ]
        )
        assert s.respond("bye", []) is None


class TestRespondTemplating:
    def test_interpolates_match_vars(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "order "},
                    "respond": {"text": "You asked about {input}"},
                }
            ]
        )
        assert s.respond("order 42", []) == ("You asked about 42", True)

    def test_interpolates_message_and_raw(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "respond": {"text": "raw={raw} msg={message}"},
                }
            ]
        )
        assert s.respond("  Hello  ", []) == ("raw=Hello msg=hello", True)

    def test_interpolates_row_columns(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "order "},
                    "query": {
                        "table": "T",
                        "select": ["status"],
                        "where": {"id": "{input}"},
                    },
                    "respond": {"text": "Order {input}: {status}"},
                }
            ]
        )
        assert s.respond("order 42", [{"status": "shipped"}]) == (
            "Order 42: shipped",
            True,
        )

    def test_missing_placeholder_left_literal(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "respond": {"text": "Hello {nope}"},
                }
            ]
        )
        assert s.respond("anything", []) == ("Hello {nope}", True)

    def test_row_column_overrides_match_var(self):
        """When a row column name collides with a match var, the row wins."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "x "},
                    "query": {
                        "table": "T",
                        "select": ["input"],
                        "where": {"id": "{input}"},
                    },
                    "respond": {"text": "got: {input}"},
                }
            ]
        )
        assert s.respond("x foo", [{"input": "bar"}]) == ("got: bar", True)


class TestRespondEmpty:
    def test_empty_rows_uses_empty_temitem(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "order "},
                    "query": {
                        "table": "T",
                        "select": ["status"],
                        "where": {"id": "{input}"},
                    },
                    "respond": {
                        "text": "Order {input}: {status}",
                        "empty": "Order {input} not found.",
                    },
                }
            ]
        )
        assert s.respond("order 42", []) == ("Order 42 not found.", True)

    def test_empty_rows_no_empty_temitem_returns_none(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "order "},
                    "query": {
                        "table": "T",
                        "select": ["status"],
                        "where": {"id": "{input}"},
                    },
                    "respond": {"text": "Order {input}: {status}"},
                }
            ]
        )
        assert s.respond("order 42", []) is None

    def test_empty_temitem_respects_quote_flag(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"prefix": "order "},
                    "query": {
                        "table": "T",
                        "select": ["status"],
                        "where": {"id": "{input}"},
                    },
                    "respond": {
                        "text": "ok",
                        "empty": "not found",
                        "quote": False,
                    },
                }
            ]
        )
        assert s.respond("order 42", []) == ("not found", False)


class TestRespondWhitespace:
    def test_literal_unresolved_placeholder_not_blank(self):
        """An unresolved `{input}` is not treated as blank — verifies that
        the whitespace-skip refinement only catches truly empty text."""
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "respond": {"text": "{input}"},
                }
            ]
        )
        # `any` matches but doesn't set {input}; the literal stays.
        assert s.respond("hello", []) == ("{input}", True)

    def test_pure_whitespace_text_returns_none(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "respond": {"text": "   "},
                }
            ]
        )
        assert s.respond("hello", []) is None

    def test_empty_text_returns_none(self):
        s = make_strategy(
            [
                {
                    "name": "test",
                    "match": {"any": True},
                    "respond": {"text": ""},
                }
            ]
        )
        assert s.respond("hello", []) is None


class TestRespondValidation:
    def test_rejects_non_dict_respond(self):
        with pytest.raises(ValueError, match="respond must be a dict"):
            make_strategy(
                [
                    {
                        "name": "t",
                        "match": {"any": True},
                        "respond": "Welcome!",
                    }
                ]
            )

    def test_rejects_missing_text(self):
        with pytest.raises(ValueError, match="respond.text is required"):
            make_strategy(
                [
                    {
                        "name": "t",
                        "match": {"any": True},
                        "respond": {"quote": True},
                    }
                ]
            )

    def test_rejects_non_string_text(self):
        with pytest.raises(ValueError, match="respond.text must be a string"):
            make_strategy(
                [
                    {
                        "name": "t",
                        "match": {"any": True},
                        "respond": {"text": 42},
                    }
                ]
            )

    def test_rejects_non_string_empty(self):
        with pytest.raises(ValueError, match="respond.empty must be a string"):
            make_strategy(
                [
                    {
                        "name": "t",
                        "match": {"any": True},
                        "respond": {"text": "x", "empty": 0},
                    }
                ]
            )

    def test_rejects_non_bool_quote(self):
        with pytest.raises(ValueError, match="respond.quote must be a bool"):
            make_strategy(
                [
                    {
                        "name": "t",
                        "match": {"any": True},
                        "respond": {"text": "x", "quote": "yes"},
                    }
                ]
            )

    def test_rejects_unknown_key(self):
        with pytest.raises(ValueError, match="respond has unknown key 'foo'"):
            make_strategy(
                [
                    {
                        "name": "t",
                        "match": {"any": True},
                        "respond": {"text": "x", "foo": 1},
                    }
                ]
            )

    def test_accepts_rule_without_respond(self):
        make_strategy(
            [{"name": "t", "match": {"any": True}, "react": {"emoji": "✅"}}]
        )

    def test_accepts_valid_respond(self):
        make_strategy(
            [
                {
                    "name": "t",
                    "match": {"any": True},
                    "respond": {
                        "text": "hi",
                        "empty": "no",
                        "quote": False,
                    },
                }
            ]
        )


class TestFuzzyQuery:
    def _strategy(self):
        return make_strategy(
            [
                {
                    "name": "inventory",
                    "match": {"prefix": "sku "},
                    "query": {
                        "table": "Inventory",
                        "select": ["SKU"],
                        "where": {"SKU": "{input}"},
                    },
                    "fuzzy": {
                        "column": "SKU",
                        "threshold": 80,
                        "limit": 3,
                        "respond": {
                            "text": "Did you mean:\n{candidates}",
                            "item": "{SKU} ({score}%)",
                        },
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )

    def test_returns_select_star_for_matched_rule_table(self):
        s = self._strategy()
        sql, args, cfg = s.fuzzy_query("sku ABC")
        assert sql == "SELECT * FROM Inventory"
        assert args == []
        assert cfg["column"] == "SKU"
        assert cfg["threshold"] == 80
        assert cfg["limit"] == 3

    def test_returns_none_when_rule_has_no_fuzzy_block(self):
        s = make_strategy(
            [
                {
                    "name": "t",
                    "match": {"prefix": "sku "},
                    "query": {
                        "table": "Inventory",
                        "select": ["SKU"],
                        "where": {"SKU": "{input}"},
                    },
                    "react": {"emoji": "✅"},
                }
            ]
        )
        assert s.fuzzy_query("sku ABC") is None

    def test_returns_none_when_no_rule_matches(self):
        s = self._strategy()
        assert s.fuzzy_query("hello") is None


class TestReactFuzzy:
    def _strategy(self, react_def=None):
        rule = {
            "name": "inventory",
            "match": {"prefix": "sku "},
            "query": {
                "table": "Inventory",
                "select": ["SKU"],
                "where": {"SKU": "{input}"},
            },
            "fuzzy": {
                "column": "SKU",
                "respond": {
                    "text": "Did you mean:\n{candidates}",
                    "item": "{SKU}",
                },
            },
            "react": {"emoji": "✅"},
        }
        if react_def is not None:
            rule["fuzzy"]["react"] = react_def
        return make_strategy([rule])

    def test_returns_configured_emoji(self):
        s = self._strategy(react_def={"emoji": "🤔"})
        assert s.react_fuzzy("sku ABC", [{"SKU": "ABC-123", "score": 85}]) == "🤔"

    def test_returns_none_when_no_fuzzy_react(self):
        s = self._strategy()  # no fuzzy.react
        assert s.react_fuzzy("sku ABC", [{"SKU": "ABC-123", "score": 85}]) is None

    def test_returns_none_when_no_rule_matches(self):
        s = self._strategy(react_def={"emoji": "🤔"})
        assert s.react_fuzzy("hello", []) is None


class TestRespondFuzzy:
    def _strategy(self, respond_def=None, item="{SKU} ({score}%)", separator=None, quote=None):
        rule = {
            "name": "inventory",
            "match": {"prefix": "sku "},
            "query": {
                "table": "Inventory",
                "select": ["SKU"],
                "where": {"SKU": "{input}"},
            },
            "fuzzy": {
                "column": "SKU",
                "respond": respond_def
                or {
                    "text": "Did you mean:\n{candidates}",
                    "item": item,
                },
            },
            "react": {"emoji": "✅"},
        }
        if separator is not None:
            rule["fuzzy"]["respond"]["separator"] = separator
        if quote is not None:
            rule["fuzzy"]["respond"]["quote"] = quote
        return make_strategy([rule])

    def test_renders_single_item(self):
        s = self._strategy()
        rows = [{"SKU": "ABC-123", "score": 87}]
        assert s.respond_fuzzy("sku ABX", rows) == (
            "Did you mean:\nABC-123 (87%)",
            True,
        )

    def test_renders_multiple_items_default_separator(self):
        s = self._strategy()
        rows = [
            {"SKU": "ABC-123", "score": 87},
            {"SKU": "ABD-122", "score": 82},
        ]
        assert s.respond_fuzzy("sku ABX", rows) == (
            "Did you mean:\nABC-123 (87%)\nABD-122 (82%)",
            True,
        )

    def test_renders_with_custom_separator(self):
        s = self._strategy(separator=" | ")
        rows = [
            {"SKU": "ABC-123", "score": 87},
            {"SKU": "ABD-122", "score": 82},
        ]
        assert s.respond_fuzzy("sku ABX", rows)[0] == (
            "Did you mean:\nABC-123 (87%) | ABD-122 (82%)"
        )

    def test_interpolates_match_vars_in_text_and_item(self):
        s = self._strategy(
            respond_def={
                "text": "Closest to {input}:\n{candidates}",
                "item": "{SKU} for {input}",
            }
        )
        rows = [{"SKU": "ABC-123", "score": 90}]
        assert s.respond_fuzzy("sku XYZ", rows) == (
            "Closest to XYZ:\nABC-123 for XYZ",
            True,
        )

    def test_quote_false_passes_through(self):
        s = self._strategy(quote=False)
        rows = [{"SKU": "ABC-123", "score": 87}]
        _text, quote = s.respond_fuzzy("sku ABX", rows)
        assert quote is False

    def test_returns_none_when_no_rule_matches(self):
        s = self._strategy()
        assert s.respond_fuzzy("hello", [{"SKU": "X", "score": 0}]) is None

    def test_returns_none_when_fuzzy_rows_empty(self):
        s = self._strategy()
        assert s.respond_fuzzy("sku ABX", []) is None

    def test_whitespace_rendered_text_returns_none(self):
        s = self._strategy(
            respond_def={"text": "{candidates}", "item": "   "}
        )
        rows = [{"SKU": "X", "score": 0}]
        assert s.respond_fuzzy("sku ABX", rows) is None


class TestFuzzyValidation:
    def _rule_with_fuzzy(self, fuzzy_def):
        return {
            "name": "t",
            "match": {"prefix": "sku "},
            "query": {
                "table": "Inventory",
                "select": ["SKU"],
                "where": {"SKU": "{input}"},
            },
            "fuzzy": fuzzy_def,
            "react": {"emoji": "✅"},
        }

    def _valid_respond(self):
        return {
            "text": "Did you mean:\n{candidates}",
            "item": "{SKU}",
        }

    def test_rejects_non_dict_fuzzy(self):
        with pytest.raises(ValueError, match="fuzzy must be a dict"):
            make_strategy([self._rule_with_fuzzy("not a dict")])

    def test_rejects_missing_column(self):
        with pytest.raises(ValueError, match="fuzzy.column is required"):
            make_strategy([self._rule_with_fuzzy({"respond": self._valid_respond()})])

    def test_rejects_non_string_column(self):
        with pytest.raises(ValueError, match="fuzzy.column must be a string"):
            make_strategy(
                [self._rule_with_fuzzy({"column": 42, "respond": self._valid_respond()})]
            )

    def test_rejects_fuzzy_without_query_table(self):
        rule = {
            "name": "t",
            "match": {"any": True},
            "fuzzy": {"column": "SKU", "respond": self._valid_respond()},
            "react": {"emoji": "✅"},
        }
        with pytest.raises(ValueError, match="fuzzy requires the rule to define query.table"):
            make_strategy([rule])

    def test_rejects_bad_threshold(self):
        with pytest.raises(ValueError, match="fuzzy.threshold must be an int between 0 and 100"):
            make_strategy(
                [
                    self._rule_with_fuzzy(
                        {
                            "column": "SKU",
                            "threshold": 150,
                            "respond": self._valid_respond(),
                        }
                    )
                ]
            )

    def test_rejects_bad_limit(self):
        with pytest.raises(ValueError, match="fuzzy.limit must be an int between 1 and 3"):
            make_strategy(
                [
                    self._rule_with_fuzzy(
                        {
                            "column": "SKU",
                            "limit": 5,
                            "respond": self._valid_respond(),
                        }
                    )
                ]
            )

    def test_rejects_zero_limit(self):
        with pytest.raises(ValueError, match="fuzzy.limit must be an int between 1 and 3"):
            make_strategy(
                [
                    self._rule_with_fuzzy(
                        {
                            "column": "SKU",
                            "limit": 0,
                            "respond": self._valid_respond(),
                        }
                    )
                ]
            )

    def test_rejects_missing_respond(self):
        with pytest.raises(ValueError, match="fuzzy.respond is required"):
            make_strategy([self._rule_with_fuzzy({"column": "SKU"})])

    def test_rejects_missing_respond_text(self):
        with pytest.raises(ValueError, match="fuzzy.respond.text must be a non-empty string"):
            make_strategy(
                [
                    self._rule_with_fuzzy(
                        {"column": "SKU", "respond": {"item": "{SKU}"}}
                    )
                ]
            )

    def test_rejects_missing_respond_item(self):
        with pytest.raises(ValueError, match="fuzzy.respond.item must be a non-empty string"):
            make_strategy(
                [
                    self._rule_with_fuzzy(
                        {
                            "column": "SKU",
                            "respond": {"text": "{candidates}"},
                        }
                    )
                ]
            )

    def test_rejects_text_without_candidates_placeholder(self):
        with pytest.raises(ValueError, match=r"fuzzy.respond.text must reference \{candidates\}"):
            make_strategy(
                [
                    self._rule_with_fuzzy(
                        {
                            "column": "SKU",
                            "respond": {"text": "no placeholder", "item": "{SKU}"},
                        }
                    )
                ]
            )

    def test_rejects_bad_react(self):
        with pytest.raises(ValueError, match="fuzzy.react must be a dict with an emoji key"):
            make_strategy(
                [
                    self._rule_with_fuzzy(
                        {
                            "column": "SKU",
                            "react": "🤔",
                            "respond": self._valid_respond(),
                        }
                    )
                ]
            )

    def test_rejects_unknown_top_level_key(self):
        with pytest.raises(ValueError, match="fuzzy has unknown key 'foo'"):
            make_strategy(
                [
                    self._rule_with_fuzzy(
                        {
                            "column": "SKU",
                            "respond": self._valid_respond(),
                            "foo": 1,
                        }
                    )
                ]
            )

    def test_rejects_unknown_respond_key(self):
        with pytest.raises(ValueError, match="fuzzy.respond has unknown key 'bar'"):
            make_strategy(
                [
                    self._rule_with_fuzzy(
                        {
                            "column": "SKU",
                            "respond": {
                                "text": "{candidates}",
                                "item": "x",
                                "bar": 1,
                            },
                        }
                    )
                ]
            )

    def test_accepts_valid_minimal_fuzzy(self):
        make_strategy(
            [
                self._rule_with_fuzzy(
                    {"column": "SKU", "respond": self._valid_respond()}
                )
            ]
        )

    def test_accepts_valid_full_fuzzy(self):
        make_strategy(
            [
                self._rule_with_fuzzy(
                    {
                        "column": "SKU",
                        "threshold": 80,
                        "limit": 3,
                        "react": {"emoji": "🤔"},
                        "respond": {
                            "text": "Did you mean:\n{candidates}",
                            "item": "{SKU} ({score}%)",
                            "separator": "\n  ",
                            "quote": False,
                        },
                    }
                )
            ]
        )

    def test_accepts_rule_without_fuzzy(self):
        make_strategy(
            [
                {
                    "name": "t",
                    "match": {"any": True},
                    "react": {"emoji": "✅"},
                }
            ]
        )


# --- YAML file loading tests ---


class TestFromFile:
    def test_loads_example(self, tmp_path):
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
        s = YamlStrategy.from_file(str(f))
        assert s.react("ping", []) == "🏓"
