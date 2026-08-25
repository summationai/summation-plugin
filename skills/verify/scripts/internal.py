"""Internal semantic candidates are intentionally disabled.

The inventory is the machine handoff: stable ids, raw displayed text, and raw
coordinates. The host agent selects ids, determines populations and direction,
and authors every semantic check. Explicit arithmetic in a public receipt is
recomputed by receipt_math.py during acceptance.
"""
from __future__ import annotations


def check_inventory(inventory: dict, visible: str | None = None) -> list[dict]:
    """Return no semantic candidates; callers consume the raw inventory."""
    del inventory, visible
    return []
