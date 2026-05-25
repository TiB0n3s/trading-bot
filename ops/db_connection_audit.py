#!/usr/bin/env python3
"""Read-only audit for SQLite connection patterns.

This report is intentionally conservative: it flags direct assignments from
`get_connection(...)` or `sqlite3.connect(...)` so maintainers can review
whether each connection is closed explicitly or should become a `with` block.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", "venv"}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    function: str
    call: str
    target: str


class ConnectionVisitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.findings: list[Finding] = []
        self.function_stack: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        call_name = connection_call_name(node.value)
        if call_name:
            target = ", ".join(target_name(t) for t in node.targets)
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    function=self.function_stack[-1] if self.function_stack else "<module>",
                    call=call_name,
                    target=target,
                )
            )
        self.generic_visit(node)


def target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return type(node).__name__


def connection_call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None

    fn = node.func
    if isinstance(fn, ast.Name) and fn.id == "get_connection":
        return "get_connection"
    if (
        isinstance(fn, ast.Attribute)
        and fn.attr == "connect"
        and isinstance(fn.value, ast.Name)
        and fn.value.id == "sqlite3"
    ):
        return "sqlite3.connect"
    return None


def iter_python_files() -> list[Path]:
    paths: list[Path] = []
    for path in ROOT.rglob("*.py"):
        rel_parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        paths.append(path)
    return sorted(paths)


def audit_file(path: Path) -> list[Finding]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return []
    visitor = ConnectionVisitor(path)
    visitor.visit(tree)
    return visitor.findings


def main() -> int:
    findings: list[Finding] = []
    for path in iter_python_files():
        findings.extend(audit_file(path))

    print("=== SQLite connection audit ===")
    print(f"repo      : {ROOT}")
    print(f"findings  : {len(findings)}")
    print()
    print("Review these manual connection assignments for explicit close() or conversion to with blocks:")

    for finding in findings:
        rel = finding.path.relative_to(ROOT)
        print(
            f"{rel}:{finding.line} "
            f"function={finding.function} "
            f"target={finding.target} "
            f"call={finding.call}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
