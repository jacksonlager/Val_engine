"""Restricted formula language for declarative rules.

A rule declared in the policy file expresses its mark as an expression over a fixed vocabulary of
fields, e.g. ``ownership_after * deal_value * close_probability``. Only names on the
whitelist, numeric literals, the four arithmetic operators, unary minus, parentheses and
``min``/``max`` are accepted. Anything else is a parse error raised *before* the model's
output is ever trusted. This module executes no code: it walks a Python AST and
evaluates a tree of arithmetic by hand.
"""
from __future__ import annotations

import ast
from typing import Mapping


class DSLError(ValueError):
    pass


_BINOPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
_FUNCS = {"min": min, "max": max}


def parse(expr: str, allowed_fields: list[str] | tuple[str, ...], allowed_operators: list[str] | tuple[str, ...]) -> ast.Expression:
    if not isinstance(expr, str) or not expr.strip():
        raise DSLError("empty formula")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as ex:
        raise DSLError(f"formula is not a valid expression: {ex.msg}") from None
    fields = set(allowed_fields)
    ops = set(allowed_operators)

    def check(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            check(node.body)
        elif isinstance(node, ast.BinOp):
            op = _BINOPS.get(type(node.op))
            if op is None or op not in ops:
                raise DSLError(f"operator {type(node.op).__name__} is not allowed")
            check(node.left); check(node.right)
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, ast.USub):
                raise DSLError("only unary minus is allowed")
            check(node.operand)
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise DSLError(f"literal {node.value!r} is not numeric")
        elif isinstance(node, ast.Name):
            if node.id not in fields:
                raise DSLError(f"field '{node.id}' is not on the whitelist {sorted(fields)}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS or node.func.id not in ops:
                raise DSLError("only min(...) and max(...) calls are allowed")
            if node.keywords or len(node.args) < 1:
                raise DSLError(f"{node.func.id} takes positional arguments only")
            for a in node.args:
                check(a)
        else:
            raise DSLError(f"syntax element {type(node).__name__} is not allowed")

    check(tree)
    return tree


def evaluate(tree: ast.Expression, values: Mapping[str, float]) -> float:
    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BinOp):
            l, r = ev(node.left), ev(node.right)
            op = _BINOPS[type(node.op)]
            if op == "+": return l + r
            if op == "-": return l - r
            if op == "*": return l * r
            if r == 0:
                raise DSLError("division by zero")
            return l / r
        if isinstance(node, ast.UnaryOp):
            return -ev(node.operand)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in values or values[node.id] is None:
                raise DSLError(f"field '{node.id}' has no value for this event")
            return float(values[node.id])
        if isinstance(node, ast.Call):
            return float(_FUNCS[node.func.id](*(ev(a) for a in node.args)))
        raise DSLError(f"unexpected node {type(node).__name__}")
    return ev(tree)


def fields_used(tree: ast.Expression) -> set[str]:
    """Operand names only — never the min/max call names."""
    call_names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in call_names}
