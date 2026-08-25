"""One public severity taxonomy for verify grades."""
from __future__ import annotations

HIGH = frozenset({"critical", "major", "high"})
MEDIUM = frozenset({"moderate", "medium"})
LOW = frozenset({"minor", "low"})
PUBLIC = frozenset({"high", "medium", "low"})


def normalize_severity(value, *, contradicted: bool = False,
                       importance: str = "material") -> str | None:
    """Map common model terms onto high/medium/low.

    Unknown material contradictions default to high.
    """
    if not contradicted:
        return None
    text = str(value or "").strip().lower()
    if text in HIGH:
        return "high"
    if text in MEDIUM:
        return "medium"
    if text in LOW:
        return "low"
    if importance == "material":
        return "high"
    if text:
        return "high"
    return "medium"
