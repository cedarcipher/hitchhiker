"""E2E test fixtures — real components wired to stub servers."""

import pytest
import pytest_asyncio

from bot.db import GristClient
from bot.yaml_strategy import YamlStrategy

from .stubs.grist_stub import GristStub


# --- Constants ---

BOT_UUID = "e2e-bot-uuid-1111-2222-3333"
SENDER_UUID = "e2e-sender-uuid-aaaa-bbbb-cccc"
SENDER_NUMBER = "+15551234567"


# --- Stub fixtures ---


@pytest_asyncio.fixture()
async def grist_stub():
    """Start and stop a Grist stub server for the duration of a test."""
    stub = GristStub()
    await stub.start()
    yield stub
    await stub.stop()


# --- Component fixtures ---


@pytest_asyncio.fixture()
async def grist_client(grist_stub):
    """A real GristClient pointed at the stub server."""
    client = GristClient(
        api_url=grist_stub.base_url,
        api_key="test-api-key",
        doc_id="test-doc-id",
    )
    yield client
    await client.close()


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
                            "values": {"1": "✅", "0": "\U0001F6AB"},
                        },
                        "empty": "❓",
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
                                "delivered": "✅",
                                "cancelled": "❌",
                            },
                            "default": "⏳",
                        },
                        "empty": "❓",
                    },
                }
            ]
        }
    )
