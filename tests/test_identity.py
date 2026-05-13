"""Tests for SignalIdentityClient — error detection + trust API."""

import httpx
import pytest

from bot.identity import SignalIdentityClient


def make_client():
    return SignalIdentityClient(
        signal_service_url="signal-api:8080",
        phone_number="+15551234567",
    )


class TestIsUntrustedError:
    @pytest.mark.parametrize(
        "error_text",
        [
            'Untrusted Identity for "c29e0455-d7bd-423c-..."',
            "UntrustedIdentityException: ...",
            "untrusted_identity",
            "Failed to deliver: untrusted-identity",
            "UNTRUSTED IDENTITY",
            'foo "untrusted identity" bar',
        ],
    )
    def test_matches_known_untrusted_shapes(self, error_text):
        client = make_client()
        assert client.is_untrusted_error(Exception(error_text)) is True

    @pytest.mark.parametrize(
        "error_text",
        [
            "Connection refused",
            "Rate limit exceeded",
            "",
            "404 Not Found",
            "untrusted",  # word alone is not enough — must be "untrusted identity"
            "identity verification required",
        ],
    )
    def test_does_not_match_unrelated_errors(self, error_text):
        client = make_client()
        assert client.is_untrusted_error(Exception(error_text)) is False


class TestTrust:
    def _build_client(self, handler):
        """Build a SignalIdentityClient backed by an httpx MockTransport."""
        client = SignalIdentityClient(
            signal_service_url="signal-api:8080",
            phone_number="+15551234567",
        )
        client._transport = httpx.MockTransport(handler)
        return client

    async def test_trust_puts_to_correct_url_with_correct_body(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = request.read()
            return httpx.Response(200, json={})

        client = self._build_client(handler)
        await client.trust("c29e0455-d7bd-423c-ffff-eeeeeeeeeeee")

        assert captured["method"] == "PUT"
        assert captured["url"] == (
            "http://signal-api:8080/v1/identities/+15551234567/trust/"
            "c29e0455-d7bd-423c-ffff-eeeeeeeeeeee"
        )
        assert captured["body"] == b'{"trust_all_known_keys": true}'

    async def test_trust_raises_on_4xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Identity not found"})

        client = self._build_client(handler)
        with pytest.raises(httpx.HTTPStatusError):
            await client.trust("missing-uuid")
