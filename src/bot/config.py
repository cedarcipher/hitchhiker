"""Load configuration from environment variables (with .env fallback)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    SIGNAL_SERVICE_URL: str
    SIGNAL_PHONE_NUMBER: str
    GRIST_API_URL: str
    GRIST_API_KEY: str
    GRIST_DOC_ID: str
    STRATEGY_PATH: str
    RATE_LIMIT_MAX: int
    RATE_LIMIT_WINDOW: int


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


settings = Settings(
    SIGNAL_SERVICE_URL=os.environ.get("SIGNAL_SERVICE_URL", "localhost:8080"),
    SIGNAL_PHONE_NUMBER=_require("SIGNAL_PHONE_NUMBER"),
    GRIST_API_URL=os.environ.get("GRIST_API_URL", "http://grist:8484"),
    GRIST_API_KEY=_require("GRIST_API_KEY"),
    GRIST_DOC_ID=_require("GRIST_DOC_ID"),
    STRATEGY_PATH=os.environ.get("STRATEGY_PATH", "/app/strategy.yaml"),
    RATE_LIMIT_MAX=int(os.environ.get("RATE_LIMIT_MAX", "10")),
    RATE_LIMIT_WINDOW=int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
)
