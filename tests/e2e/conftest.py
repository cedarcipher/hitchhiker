"""E2E test fixtures — real components wired to stub servers."""

import asyncio

import pytest

from bot.commands import RateLimiter, ReactCommand
from bot.db import GristClient
from bot.yaml_strategy import YamlStrategy

from .stubs.grist_stub import GristStub


# --- Constants ---

BOT_UUID = "e2e-bot-uuid-1111-2222-3333"
SENDER_UUID = "e2e-sender-uuid-aaaa-bbbb-cccc"
SENDER_NUMBER = "+15551234567"


# --- Stub fixtures ---


@pytest.fixture(autouse=True)
def _event_loop():
    """Create and set an explicit event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture()
def grist_stub(_event_loop):
    """Start and stop a Grist stub server for the duration of a test."""
    stub = GristStub()
    _event_loop.run_until_complete(stub.start())
    yield stub
    _event_loop.run_until_complete(stub.stop())


# --- Component fixtures ---


@pytest.fixture()
def grist_client(grist_stub, _event_loop):
    """A real GristClient pointed at the stub server."""
    client = GristClient(
        api_url=grist_stub.base_url,
        api_key="test-api-key",
        doc_id="test-doc-id",
    )
    yield client
    _event_loop.run_until_complete(client.close())


@pytest.fixture()
def stock_strategy():
    """The stock-check strategy from OVERVIEW.md / README."""
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


@pytest.fixture()
def order_strategy():
    """The order-status strategy from examples/order_status.yaml."""
    return YamlStrategy(
        {
            "rules": [
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
                                "cancelled": "\u274C",
                            },
                            "default": "\u23F3",
                        },
                        "empty": "\u2753",
                    },
                }
            ]
        }
    )
