"""YAML strategy — compiles a declarative YAML definition into query()/react() calls."""

import re

import yaml


class YamlStrategy:
    """Strategy compiled from a declarative YAML definition."""

    def __init__(self, config: dict) -> None:
        self.rules = config.get("rules", [])
        self.tables = config.get("tables", {})

    @classmethod
    def from_file(cls, path: str) -> "YamlStrategy":
        with open(path) as f:
            return cls(yaml.safe_load(f))

    def query(self, message_text: str) -> tuple[str, list]:
        text = message_text.strip()
        for rule in self.rules:
            variables = self._match(rule.get("match", {}), text)
            if variables is None:
                continue

            query_def = rule.get("query")
            if not query_def:
                return ("", [])  # no query, but react() will still run

            return self._build_query(query_def, variables)

        return ("", [])  # no rule matched

    def react(self, message_text: str, rows: list[dict]) -> str | None:
        text = message_text.strip()
        for rule in self.rules:
            variables = self._match(rule.get("match", {}), text)
            if variables is None:
                continue

            react_def = rule.get("react")
            if not react_def:
                return None

            return self._evaluate_react(react_def, rows)

        return None

    # --- Match engine ---

    def _match(self, match_def: dict, text: str) -> dict | None:
        """Return template variables if matched, None otherwise."""
        message = text.lower().strip()
        variables = {"message": message, "raw": text}

        if match_def.get("any"):
            return variables

        if "prefix" in match_def:
            prefix = match_def["prefix"]
            if text.lower().startswith(prefix.lower()):
                variables["input"] = text[len(prefix) :].strip()
                return variables
            return None

        if "suffix" in match_def:
            suffix = match_def["suffix"]
            if text.lower().endswith(suffix.lower()):
                variables["input"] = text[: -len(suffix)].strip()
                return variables
            return None

        if "exact" in match_def:
            if message == match_def["exact"].lower():
                return variables
            return None

        if "contains" in match_def:
            if match_def["contains"].lower() in message:
                return variables
            return None

        if "regex" in match_def:
            m = re.search(match_def["regex"], text, re.IGNORECASE)
            if m:
                if m.groups():
                    variables["input"] = m.group(1).strip()
                return variables
            return None

        return None

    # --- Query builder ---

    def _build_query(
        self, query_def: dict, variables: dict
    ) -> tuple[str, list]:
        # Raw SQL mode
        if "sql" in query_def:
            sql = query_def["sql"]
            args = [
                self._interpolate(a, variables)
                for a in query_def.get("args", [])
            ]
            return (sql, args)

        # Structured query mode
        table = query_def["table"]
        select = query_def.get("select", ["*"])
        where = query_def.get("where", {})

        cols = ", ".join(select) if select != ["*"] else "*"
        conditions = []
        args = []
        for col, val in where.items():
            interpolated = self._interpolate(val, variables)
            conditions.append(f"LOWER({col}) = ?")
            args.append(str(interpolated).lower())

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT {cols} FROM {table} WHERE {where_clause}"

        if "limit" in query_def:
            sql += f" LIMIT {int(query_def['limit'])}"

        return (sql, args)

    def _interpolate(self, value, variables: dict) -> str:
        """Replace {message}, {input}, {raw} placeholders with actual values."""
        if isinstance(value, str):
            for key, val in variables.items():
                value = value.replace(f"{{{key}}}", str(val))
        return value

    # --- React evaluator ---

    def _evaluate_react(
        self, react_def: dict, rows: list[dict]
    ) -> str | None:
        # Static emoji — if no empty handler is defined, always return it
        # (supports no-query rules like "ping" → "🏓").
        # When empty is defined alongside emoji, it acts as an existence check:
        # emoji for found, empty for not found.
        if "emoji" in react_def:
            if not rows and "empty" in react_def:
                return react_def["empty"]
            return react_def["emoji"]

        # No rows — use the empty handler
        if not rows:
            return react_def.get("empty")  # None means no reaction

        # Use a column's value directly as the emoji
        if "column" in react_def and "map" not in react_def:
            return rows[0].get(react_def["column"])

        # Map a column value to an emoji via a lookup table
        if "map" in react_def:
            map_def = react_def["map"]
            value = str(rows[0].get(map_def["column"], "")).lower()
            values = {str(k).lower(): v for k, v in map_def.get("values", {}).items()}
            return values.get(value, map_def.get("default"))

        return None
