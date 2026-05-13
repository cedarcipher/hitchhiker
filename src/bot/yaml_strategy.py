"""YAML strategy — compiles a declarative YAML definition into query()/react() calls."""

import re

import yaml


class YamlStrategy:
    """Strategy compiled from a declarative YAML definition."""

    _LEAF_KEYS = ("prefix", "suffix", "exact", "contains", "regex", "any")
    _MATCH_KEYS = ("any_of", "all_of") + _LEAF_KEYS
    _RESPOND_KEYS = ("text", "empty", "quote")
    _FUZZY_KEYS = ("column", "threshold", "limit", "react", "respond")
    _FUZZY_RESPOND_KEYS = ("text", "item", "separator", "quote")

    def __init__(self, config: dict) -> None:
        self.rules = config.get("rules", [])
        self.tables = config.get("tables", {})
        for rule in self.rules:
            self._validate_match(rule.get("match", {}))
            self._validate_respond(rule.get("respond"))
            self._validate_fuzzy(rule.get("fuzzy"), rule)

    @classmethod
    def _validate_match(cls, match_def: dict) -> None:
        present = [k for k in cls._MATCH_KEYS if k in match_def]
        if len(present) != 1:
            raise ValueError(
                "match must have exactly one of: " + ", ".join(cls._MATCH_KEYS)
            )
        key = present[0]
        if key in ("any_of", "all_of"):
            items = match_def[key]
            if not items:
                raise ValueError(
                    f"{key} must contain at least one matcher"
                )
            for sub in items:
                cls._validate_match(sub)

    @classmethod
    def _validate_respond(cls, respond_def) -> None:
        if respond_def is None:
            return
        if not isinstance(respond_def, dict):
            raise ValueError("respond must be a dict")
        if "text" not in respond_def:
            raise ValueError("respond.text is required")
        if not isinstance(respond_def["text"], str):
            raise ValueError("respond.text must be a string")
        if "empty" in respond_def and not isinstance(respond_def["empty"], str):
            raise ValueError("respond.empty must be a string")
        if "quote" in respond_def and not isinstance(respond_def["quote"], bool):
            raise ValueError("respond.quote must be a bool")
        for key in respond_def:
            if key not in cls._RESPOND_KEYS:
                raise ValueError(f"respond has unknown key '{key}'")

    @classmethod
    def _validate_fuzzy(cls, fuzzy_def, rule: dict) -> None:
        if fuzzy_def is None:
            return
        if not isinstance(fuzzy_def, dict):
            raise ValueError("fuzzy must be a dict")
        if "column" not in fuzzy_def:
            raise ValueError("fuzzy.column is required")
        if not isinstance(fuzzy_def["column"], str):
            raise ValueError("fuzzy.column must be a string")
        query_def = rule.get("query") or {}
        if "table" not in query_def:
            raise ValueError("fuzzy requires the rule to define query.table")
        if "threshold" in fuzzy_def:
            t = fuzzy_def["threshold"]
            if not isinstance(t, int) or isinstance(t, bool) or not 0 <= t <= 100:
                raise ValueError(
                    "fuzzy.threshold must be an int between 0 and 100"
                )
        if "limit" in fuzzy_def:
            lim = fuzzy_def["limit"]
            if not isinstance(lim, int) or isinstance(lim, bool) or not 1 <= lim <= 3:
                raise ValueError(
                    "fuzzy.limit must be an int between 1 and 3"
                )
        if "respond" not in fuzzy_def:
            raise ValueError("fuzzy.respond is required")
        respond_def = fuzzy_def["respond"]
        if not isinstance(respond_def, dict):
            raise ValueError("fuzzy.respond must be a dict")
        text = respond_def.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("fuzzy.respond.text must be a non-empty string")
        item = respond_def.get("item")
        if not isinstance(item, str) or not item:
            raise ValueError("fuzzy.respond.item must be a non-empty string")
        if "{candidates}" not in text:
            raise ValueError("fuzzy.respond.text must reference {candidates}")
        if "react" in fuzzy_def:
            react_def = fuzzy_def["react"]
            if not (
                isinstance(react_def, dict)
                and isinstance(react_def.get("emoji"), str)
            ):
                raise ValueError(
                    "fuzzy.react must be a dict with an emoji key"
                )
        for key in fuzzy_def:
            if key not in cls._FUZZY_KEYS:
                raise ValueError(f"fuzzy has unknown key '{key}'")
        for key in respond_def:
            if key not in cls._FUZZY_RESPOND_KEYS:
                raise ValueError(f"fuzzy.respond has unknown key '{key}'")

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

    def respond(
        self, message_text: str, rows: list[dict]
    ) -> tuple[str, bool] | None:
        """Return (text, quote) for a text reply, or None for no reply."""
        text = message_text.strip()
        for rule in self.rules:
            variables = self._match(rule.get("match", {}), text)
            if variables is None:
                continue

            respond_def = rule.get("respond")
            if not respond_def:
                return None

            quote = respond_def.get("quote", True)
            has_query = bool(rule.get("query"))

            if has_query and not rows:
                empty = respond_def.get("empty")
                if empty is None:
                    return None
                rendered = self._interpolate(empty, variables)
            else:
                row_vars = rows[0] if rows else {}
                merged = {**variables, **row_vars}
                rendered = self._interpolate(respond_def["text"], merged)

            if not rendered.strip():
                return None
            return (rendered, quote)

        return None

    def fuzzy_query(
        self, message_text: str
    ) -> tuple[str, list, dict, str] | None:
        """Return (sql, args, fuzzy_cfg, fuzzy_input) for the candidate-pool
        query, or None if the matched rule has no fuzzy: block.

        ``fuzzy_input`` is the value to fuzzy-match against the column: the
        rule's captured ``{input}`` if the matcher set one (prefix/suffix/regex
        with a group), otherwise the full stripped message text.
        """
        text = message_text.strip()
        for rule in self.rules:
            variables = self._match(rule.get("match", {}), text)
            if variables is None:
                continue
            fuzzy_def = rule.get("fuzzy")
            if not fuzzy_def:
                return None
            table = rule["query"]["table"]
            fuzzy_input = variables.get("input", text)
            return (f"SELECT * FROM {table}", [], fuzzy_def, fuzzy_input)
        return None

    def react_fuzzy(
        self, message_text: str, fuzzy_rows: list[dict]
    ) -> str | None:
        """Return emoji for the fuzzy branch, or None."""
        text = message_text.strip()
        for rule in self.rules:
            if self._match(rule.get("match", {}), text) is None:
                continue
            fuzzy_def = rule.get("fuzzy") or {}
            react_def = fuzzy_def.get("react") or {}
            return react_def.get("emoji")
        return None

    def respond_fuzzy(
        self, message_text: str, fuzzy_rows: list[dict]
    ) -> tuple[str, bool] | None:
        """Render fuzzy.respond. Returns (text, quote) or None."""
        if not fuzzy_rows:
            return None
        text = message_text.strip()
        for rule in self.rules:
            variables = self._match(rule.get("match", {}), text)
            if variables is None:
                continue
            fuzzy_def = rule.get("fuzzy") or {}
            respond_def = fuzzy_def.get("respond")
            if not respond_def:
                return None
            item_tmpl = respond_def["item"]
            separator = respond_def.get("separator", "\n")
            quote = respond_def.get("quote", True)

            rendered_items = [
                self._interpolate(item_tmpl, {**variables, **row})
                for row in fuzzy_rows
            ]
            candidates = separator.join(rendered_items)
            text_vars = {**variables, "candidates": candidates}
            rendered = self._interpolate(respond_def["text"], text_vars)

            if not rendered.strip():
                return None
            return (rendered, quote)
        return None

    # --- Match engine ---

    def _match(self, match_def: dict, text: str) -> dict | None:
        """Return template variables if matched, None otherwise."""
        message = text.lower().strip()
        variables = {"message": message, "raw": text}

        if "any_of" in match_def:
            fallback = None
            for sub in match_def["any_of"]:
                result = self._match(sub, text)
                if result is None:
                    continue
                if "input" in result:
                    return result
                if fallback is None:
                    fallback = result
            return fallback

        if "all_of" in match_def:
            merged = {"message": message, "raw": text}
            for sub in match_def["all_of"]:
                result = self._match(sub, text)
                if result is None:
                    return None
                if "input" in result:
                    merged["input"] = result["input"]
            return merged

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
