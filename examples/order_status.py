# Example: order status lookup (Python strategy)
#
# Equivalent to order_status.yaml but with full programmatic control.
# Use this as a template for complex strategies that need Python logic.


class Strategy:
    def query(self, message_text: str) -> tuple[str, list]:
        text = message_text.strip()
        if not text.lower().startswith("order "):
            return ("", [])
        order_id = text[len("order ") :].strip()
        return ("SELECT status FROM Orders WHERE LOWER(order_id) = ?", [order_id.lower()])

    def react(self, message_text: str, rows: list[dict]) -> str | None:
        if not rows:
            return "\u2753"  # ❓
        status = rows[0]["status"]
        return {
            "shipped": "\U0001F4E6",   # 📦
            "delivered": "\u2705",      # ✅
            "cancelled": "\u274C",      # ❌
        }.get(status, "\u23F3")        # ⏳
