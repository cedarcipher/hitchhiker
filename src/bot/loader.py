"""Unified strategy loader — detects format by file extension."""

import importlib.util
from pathlib import Path


def load_strategy(path: str):
    """
    Load a strategy from a file path.

    - .yaml / .yml  → parse as YAML, return YamlStrategy
    - .py           → import module, return first class with query() and react()
    """
    ext = Path(path).suffix.lower()

    if ext in (".yaml", ".yml"):
        from bot.yaml_strategy import YamlStrategy

        return YamlStrategy.from_file(path)

    if ext == ".py":
        spec = importlib.util.spec_from_file_location("strategy", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for obj in vars(mod).values():
            if (
                isinstance(obj, type)
                and hasattr(obj, "query")
                and hasattr(obj, "react")
            ):
                return obj()
        raise RuntimeError(f"No Strategy class found in {path}")

    raise RuntimeError(
        f"Unsupported strategy file format: {ext} (use .yaml or .py)"
    )
