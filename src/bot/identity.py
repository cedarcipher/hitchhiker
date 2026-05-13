"""Client for the signal-cli-rest-api identity surface.

Owns two responsibilities:

1. Detecting when an exception raised during message send indicates that the
   recipient's Signal identity is untrusted (safety number changed).
2. Trusting a UUID, equivalent to ``signal-cli -a <bot_number> trust -a <uuid>``.

See docs/superpowers/specs/2026-05-12-auto-retrust-design.md.
"""

import json
import re

import httpx


class SignalIdentityClient:
    def __init__(self, signal_service_url: str, phone_number: str) -> None:
        self.signal_service_url = signal_service_url
        self.phone_number = phone_number
        # Injectable for tests; production code leaves this None so a fresh
        # AsyncClient is constructed per call.
        self._transport: httpx.AsyncBaseTransport | None = None

    def is_untrusted_error(self, exc: BaseException) -> bool:
        """Return True if exc indicates an untrusted-identity failure.

        Heuristic: signal-cli surfaces these failures with strings such as
        ``Untrusted Identity for "<uuid>"`` or ``UntrustedIdentityException``.
        We normalize the exception text to letters-only and look for the two
        words run together, which catches every separator/case variant.
        """
        normalized = re.sub(r"[^a-z]", "", str(exc).lower())
        return "untrustedidentity" in normalized

    async def trust(self, uuid: str) -> None:
        """Trust all known keys for ``uuid``.

        Equivalent to ``signal-cli -a <bot_number> trust -a <uuid>``.
        The bot's phone number scopes the request to the bot's account.
        """
        url = (
            f"http://{self.signal_service_url}"
            f"/v1/identities/{self.phone_number}/trust/{uuid}"
        )
        async with httpx.AsyncClient(
            transport=self._transport, timeout=10
        ) as client:
            resp = await client.put(
                url,
                content=json.dumps({"trust_all_known_keys": True}),
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
