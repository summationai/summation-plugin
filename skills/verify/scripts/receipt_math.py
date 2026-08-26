#!/usr/bin/env python3
"""Restricted arithmetic for agent-authored public receipt calculations."""
from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation
import re


_RESULT = re.compile(
    r"^\s*\$?\s*(?P<number>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?:%|pp|percent(?:age)?(?:\s+points?)?|points?|bps|basis\s+points?)?\s*$",
    re.I,
)
_ALLOWED = re.compile(r"^[\d\s.,()+\-*/]+$")


def public_number(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    match = _RESULT.fullmatch(str(value))
    if not match:
        return None
    try:
        return Decimal(match.group("number").replace(",", ""))
    except InvalidOperation:
        return None


def _evaluate(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("division by zero")
            return left / right
    raise ValueError("unsupported arithmetic syntax")


def _literals(node: ast.AST) -> list[Decimal]:
    if isinstance(node, ast.Expression):
        return _literals(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return [Decimal(str(node.value))]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        values = _literals(node.operand)
        return values if isinstance(node.op, ast.UAdd) else [-value for value in values]
    if isinstance(node, ast.BinOp):
        return [*_literals(node.left), *_literals(node.right)]
    return []


def calculation_problem(expression, result, operands: list[dict]) -> str | None:
    """Validate and recompute a numeric expression without interpreting prose."""
    raw = str(expression or "").strip()
    normalized = raw.replace("×", "*").replace("÷", "/").replace("$", "")
    normalized = normalized.replace(",", "")
    if not normalized or len(normalized) > 500 or not _ALLOWED.fullmatch(normalized):
        return "calculation expression must contain numeric arithmetic only"
    try:
        tree = ast.parse(normalized, mode="eval")
        if sum(1 for _node in ast.walk(tree)) > 100:
            return "calculation expression is too complex"
        computed = _evaluate(tree)
    except (SyntaxError, ValueError, InvalidOperation):
        return "calculation expression is not valid restricted arithmetic"
    literals = _literals(tree)
    if len(literals) < 2:
        return "calculation expression needs at least two numeric operands"
    declared_values = {
        value for value in (
            public_number(row.get("value"))
            for row in operands if isinstance(row, dict)
        ) if value is not None
    }
    used_values = set(literals)
    unexplained = used_values - declared_values - {Decimal("100")}
    if unexplained:
        return "calculation expression uses a value absent from decisive_operands"
    declared_result = public_number(result)
    if declared_result is None:
        return "calculation result is not a public numeric value"
    tolerance = Decimal("0.000000001")
    if abs(computed - declared_result) > tolerance:
        return "calculation result does not equal the computed expression"
    return None
