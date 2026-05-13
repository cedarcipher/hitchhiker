"""Tests for the ReactCommand handler with mocked dependencies."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from bot.commands import RateLimiter, ReactCommand
from bot.identity import SignalIdentityClient


# --- Constants ---

BOT_UUID = "bot-uuid-1234-5678"
OTHER_UUID = "other-uuid-9999-0000"
SENDER_UUID = "sender-uuid-aaaa-bbbb"


# --- Fixtures ---


class FakeStrategy:
    """A simple fake strategy for testing."""

    def __init__(self, sql="", args=None, emoji=None):
        self._sql = sql
        self._args = args or []
        self._emoji = emoji

    def query(self, message_text):
        return (self._sql, self._args)

    def react(self, message_text, rows):
        return self._emoji


def make_context(text="hello", group=None, mentions=None, source_uuid=SENDER_UUID):
    """Create a mock signalbot Context."""
    ctx = MagicMock()
    ctx.message = MagicMock()
    ctx.message.text = text
    ctx.message.group = group
    ctx.message.mentions = mentions or []
    ctx.message.source_uuid = source_uuid
    ctx.react = AsyncMock()
    return ctx


def make_db(rows=None):
    """Create a mock GristClient."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=rows or [])
    return db


# --- Tests ---


class TestReactCommand:
    def test_reacts_with_emoji(self):
        db = make_db(rows=[{"status": "shipped"}])
        strategy = FakeStrategy(
            sql="SELECT status FROM T WHERE id = ?",
            args=["123"],
            emoji="📦",
        )
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("order 123")

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        db.execute.assert_awaited_once_with(
            "SELECT status FROM T WHERE id = ?", ["123"]
        )
        ctx.react.assert_awaited_once_with("📦")

    def test_no_query_still_reacts(self):
        db = make_db()
        strategy = FakeStrategy(sql="", args=[], emoji="🏓")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("ping")

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        db.execute.assert_not_awaited()
        ctx.react.assert_awaited_once_with("🏓")

    def test_no_emoji_skips_react(self):
        db = make_db()
        strategy = FakeStrategy(sql="", args=[], emoji=None)
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("unmatched")

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_not_awaited()

    def test_empty_message_skips(self):
        db = make_db()
        strategy = FakeStrategy(emoji="📦")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("")

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_not_awaited()

    def test_none_message_skips(self):
        db = make_db()
        strategy = FakeStrategy(emoji="📦")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context(None)

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_not_awaited()

    def test_grist_error_does_not_crash(self):
        db = make_db()
        db.execute = AsyncMock(side_effect=Exception("connection refused"))
        strategy = FakeStrategy(
            sql="SELECT x FROM T", args=[], emoji="📦"
        )
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("order 123")

        # Should not raise
        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_not_awaited()


class TestMentionFiltering:
    """Tests for @-mention filtering in group chats."""

    def test_dm_without_mention_processes_normally(self):
        """Direct messages are processed without requiring an @-mention."""
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("ping", group=None, mentions=[])

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_awaited_once_with("🏓")

    def test_group_message_with_bot_mentioned_processes(self):
        """Group messages with the bot @-mentioned are processed."""
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context(
            "\uFFFC ping",
            group="group.ABC123",
            mentions=[{"uuid": BOT_UUID, "start": 0, "length": 1}],
        )

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_awaited_once_with("🏓")

    def test_group_message_without_mention_is_ignored(self):
        """Group messages without any @-mention are ignored."""
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("ping", group="group.ABC123", mentions=[])

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_not_awaited()

    def test_group_message_mentioning_someone_else_is_ignored(self):
        """Group messages mentioning a different user are ignored."""
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context(
            "\uFFFC ping",
            group="group.ABC123",
            mentions=[{"uuid": OTHER_UUID, "start": 0, "length": 1}],
        )

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_not_awaited()

    def test_mention_placeholder_is_stripped_from_text(self):
        """The U+FFFC placeholder character is stripped before strategy processing."""
        db = make_db()
        strategy = FakeStrategy(
            sql="SELECT x FROM T WHERE id = ?", args=["test"], emoji="✅"
        )
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context(
            "\uFFFC stock Bandages",
            group="group.ABC123",
            mentions=[{"uuid": BOT_UUID, "start": 0, "length": 1}],
        )

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        # Strategy receives clean text, so the command runs the full pipeline
        ctx.react.assert_awaited_once_with("✅")

    def test_mention_only_message_is_skipped(self):
        """A message with only a mention placeholder and no other text is skipped."""
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context(
            "\uFFFC",
            group="group.ABC123",
            mentions=[{"uuid": BOT_UUID, "start": 0, "length": 1}],
        )

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_not_awaited()

    def test_dm_also_strips_placeholder(self):
        """U+FFFC stripping also applies to direct messages."""
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("\uFFFC ping", group=None, mentions=[])

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_awaited_once_with("🏓")


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    def test_allows_messages_within_limit(self):
        """Messages within the limit are allowed."""
        limiter = RateLimiter(max_messages=3, window_seconds=60)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True

    def test_blocks_messages_over_limit(self):
        """Messages exceeding the limit are blocked."""
        limiter = RateLimiter(max_messages=2, window_seconds=60)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is False

    def test_different_senders_have_independent_limits(self):
        """Each sender has their own independent counter."""
        limiter = RateLimiter(max_messages=1, window_seconds=60)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-2") is True
        # user-1 is now over limit, user-2 is not
        assert limiter.is_allowed("user-1") is False
        assert limiter.is_allowed("user-2") is False

    def test_window_expiry_resets_limit(self):
        """Messages are allowed again after the window expires."""
        limiter = RateLimiter(max_messages=1, window_seconds=60)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is False

        # Simulate time passing by backdating the stored timestamp
        limiter._timestamps["user-1"] = [
            limiter._timestamps["user-1"][0] - 61
        ]
        assert limiter.is_allowed("user-1") is True

    def test_old_entries_are_pruned(self):
        """Expired timestamps are cleaned up on each check."""
        limiter = RateLimiter(max_messages=2, window_seconds=60)
        # Manually insert an old timestamp
        import time

        limiter._timestamps["user-1"] = [time.monotonic() - 120]
        # Should be pruned, leaving room for new messages
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is False


class TestRateLimitIntegration:
    """Tests for rate limiting integrated into the ReactCommand handler."""

    def test_rate_limited_message_is_silently_dropped(self):
        """Messages from a rate-limited sender are silently ignored."""
        limiter = RateLimiter(max_messages=1, window_seconds=60)
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(
            db=db, strategy=strategy, bot_uuid=BOT_UUID, rate_limiter=limiter
        )

        # First message succeeds
        ctx1 = make_context("ping", source_uuid="sender-1")
        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx1))
        ctx1.react.assert_awaited_once_with("🏓")

        # Second message from same sender is dropped
        ctx2 = make_context("ping", source_uuid="sender-1")
        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx2))
        ctx2.react.assert_not_awaited()

    def test_different_senders_not_affected_by_each_other(self):
        """Rate limiting one sender does not block another."""
        limiter = RateLimiter(max_messages=1, window_seconds=60)
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(
            db=db, strategy=strategy, bot_uuid=BOT_UUID, rate_limiter=limiter
        )

        # sender-1 uses their allowance
        ctx1 = make_context("ping", source_uuid="sender-1")
        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx1))
        ctx1.react.assert_awaited_once()

        # sender-2 is unaffected
        ctx2 = make_context("ping", source_uuid="sender-2")
        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx2))
        ctx2.react.assert_awaited_once()

    def test_no_rate_limiter_allows_all(self):
        """Without a rate limiter, all messages are processed."""
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)

        for _ in range(20):
            ctx = make_context("ping", source_uuid="sender-1")
            asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))
            ctx.react.assert_awaited_once()

    def test_rate_limit_checked_after_mention_filter(self):
        """In groups, mention filtering runs before rate limiting.

        A group message without a mention should be ignored without
        consuming a rate limit token.
        """
        limiter = RateLimiter(max_messages=1, window_seconds=60)
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(
            db=db, strategy=strategy, bot_uuid=BOT_UUID, rate_limiter=limiter
        )

        # Unmentioned group message — filtered out, no rate limit consumed
        ctx1 = make_context(
            "hello", group="group.X", mentions=[], source_uuid="sender-1"
        )
        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx1))
        ctx1.react.assert_not_awaited()

        # Mentioned message — should still work (limit not consumed above)
        ctx2 = make_context(
            "\uFFFC ping",
            group="group.X",
            mentions=[{"uuid": BOT_UUID, "start": 0, "length": 1}],
            source_uuid="sender-1",
        )
        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx2))
        ctx2.react.assert_awaited_once_with("🏓")


class TestAutoRetrust:
    """Tests for auto re-trust when a react fails due to untrusted identity."""

    def _make_identity(self):
        """A fake identity client with stubbable async methods."""
        identity = MagicMock(spec=SignalIdentityClient)
        identity.is_untrusted_error = MagicMock(return_value=False)
        identity.trust = AsyncMock()
        return identity

    def test_normal_react_does_not_call_trust(self):
        identity = self._make_identity()
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(
            db=db, strategy=strategy, bot_uuid=BOT_UUID,
            identity_client=identity,
        )
        ctx = make_context("ping")

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        ctx.react.assert_awaited_once_with("🏓")
        identity.trust.assert_not_awaited()

    def test_untrusted_react_triggers_trust_and_retry(self):
        identity = self._make_identity()
        identity.is_untrusted_error.return_value = True
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(
            db=db, strategy=strategy, bot_uuid=BOT_UUID,
            identity_client=identity,
        )
        ctx = make_context("ping", source_uuid="sender-X")
        ctx.react = AsyncMock(
            side_effect=[Exception("Untrusted Identity for sender-X"), None]
        )

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        identity.trust.assert_awaited_once_with("sender-X")
        assert ctx.react.await_count == 2
        ctx.react.assert_has_awaits([call("🏓"), call("🏓")])

    def test_trust_failure_is_contained(self):
        identity = self._make_identity()
        identity.is_untrusted_error.return_value = True
        identity.trust = AsyncMock(side_effect=Exception("network down"))
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(
            db=db, strategy=strategy, bot_uuid=BOT_UUID,
            identity_client=identity,
        )
        ctx = make_context("ping")
        ctx.react = AsyncMock(side_effect=Exception("Untrusted Identity for x"))

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        identity.trust.assert_awaited_once()
        assert ctx.react.await_count == 1

    def test_retry_failure_is_contained(self):
        identity = self._make_identity()
        identity.is_untrusted_error.return_value = True
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(
            db=db, strategy=strategy, bot_uuid=BOT_UUID,
            identity_client=identity,
        )
        ctx = make_context("ping")
        ctx.react = AsyncMock(
            side_effect=[
                Exception("Untrusted Identity for x"),
                Exception("Untrusted Identity for x"),
            ]
        )

        asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        identity.trust.assert_awaited_once()
        assert ctx.react.await_count == 2

    def test_unrelated_react_failure_propagates(self):
        identity = self._make_identity()
        identity.is_untrusted_error.return_value = False
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(
            db=db, strategy=strategy, bot_uuid=BOT_UUID,
            identity_client=identity,
        )
        ctx = make_context("ping")
        ctx.react = AsyncMock(side_effect=RuntimeError("unrelated"))

        with pytest.raises(RuntimeError, match="unrelated"):
            asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))

        identity.trust.assert_not_awaited()

    def test_without_identity_client_failure_propagates(self):
        db = make_db()
        strategy = FakeStrategy(emoji="🏓")
        cmd = ReactCommand(db=db, strategy=strategy, bot_uuid=BOT_UUID)
        ctx = make_context("ping")
        ctx.react = AsyncMock(side_effect=Exception("Untrusted Identity for x"))

        with pytest.raises(Exception, match="Untrusted Identity"):
            asyncio.get_event_loop().run_until_complete(cmd.handle(ctx))
