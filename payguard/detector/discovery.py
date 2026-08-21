"""
Discovery: identify payment-relevant code units in a repository.

A PaymentUnit is a function/route/handler that either:
  - imports razorpay or calls /v1/orders|payments|refunds
  - handles X-Razorpay-Signature
  - contains razorpay_* identifiers

Supported: Python (ast) + JS/TS (regex + tree-sitter where available).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class UnitKind(str, Enum):
    CHARGE = "CHARGE"
    WEBHOOK = "WEBHOOK"
    REFUND = "REFUND"
    CAPTURE = "CAPTURE"
    OTHER = "OTHER"


@dataclass
class PaymentUnit:
    file: str
    symbol: str
    start_line: int
    end_line: int
    kind: UnitKind
    imports: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)
    source: str = ""


# Patterns that signal payment relevance
_RAZORPAY_IMPORT_PY = re.compile(r"\brazorpay\b")
_RAZORPAY_IMPORT_JS = re.compile(r"""require\(['"]razorpay['"]\)|from ['"]razorpay['"]""")
_V1_API_CALL = re.compile(r"/v1/(orders|payments|refunds|captures)")
_WEBHOOK_SIGNAL = re.compile(r"X-Razorpay-Signature|razorpay_signature|webhook.*razorpay|razorpay.*webhook", re.I)
_RAZORPAY_ID = re.compile(r"\brazorpay_\w+\b")
_RAZORPAY_AMOUNT = re.compile(r"\b(rzp|razorpay|rp)_?(amount|order|payment)\b", re.I)


def _is_payment_relevant(source: str) -> bool:
    return bool(
        _RAZORPAY_IMPORT_PY.search(source)
        or _RAZORPAY_IMPORT_JS.search(source)
        or _V1_API_CALL.search(source)
        or _WEBHOOK_SIGNAL.search(source)
        or _RAZORPAY_ID.search(source)
    )


def _infer_kind(source: str, symbol: str) -> UnitKind:
    s = (source + " " + symbol).lower()
    if any(w in s for w in ("webhook", "signature", "x-razorpay-signature", "event")):
        return UnitKind.WEBHOOK
    if any(w in s for w in ("refund", "rfnd")):
        return UnitKind.REFUND
    if any(w in s for w in ("capture",)):
        return UnitKind.CAPTURE
    if any(w in s for w in ("order", "charge", "checkout", "payment", "pay")):
        return UnitKind.CHARGE
    return UnitKind.OTHER


class _FunctionExtractor(ast.NodeVisitor):
    """Extract function/method definitions from a Python AST."""

    def __init__(self, source_lines: list[str]) -> None:
        self.units: list[PaymentUnit] = []
        self.source_lines = source_lines
        self._file = ""
        self._imports: list[str] = []

    def set_file(self, path: str) -> None:
        self._file = path

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self._imports.append(node.module)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        end = node.end_lineno or node.lineno
        source = "\n".join(self.source_lines[node.lineno - 1 : end])
        if _is_payment_relevant(source) or _is_payment_relevant(" ".join(self._imports)):
            callees = [
                n.func.id if isinstance(n.func, ast.Name) else
                (n.func.attr if isinstance(n.func, ast.Attribute) else "?")
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and hasattr(n, "func")
            ]
            unit = PaymentUnit(
                file=self._file,
                symbol=node.name,
                start_line=node.lineno,
                end_line=end,
                kind=_infer_kind(source, node.name),
                imports=list(self._imports),
                callees=[c for c in callees if c != "?"],
                source=source,
            )
            self.units.append(unit)
        self.generic_visit(node)


def _discover_python(path: Path) -> list[PaymentUnit]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        if not _is_payment_relevant(source):
            return []
        tree = ast.parse(source, filename=str(path))
        extractor = _FunctionExtractor(source.splitlines())
        extractor.set_file(str(path))
        extractor.visit(tree)
        return extractor.units
    except SyntaxError:
        return []


# JS/TS: regex-based extraction (tree-sitter used in Phase 3+)
_JS_FUNC_RE = re.compile(
    r"(?:async\s+)?(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s+)?\(|"
    r"(?:app|router)\.\w+\(['\"][^'\"]+['\"]\s*,\s*(?:async\s+)?\()",
    re.M,
)


def _discover_js(path: Path) -> list[PaymentUnit]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        if not _is_payment_relevant(source):
            return []
        lines = source.splitlines()
        units = []
        # Simple heuristic: treat the whole file as one unit if payment-relevant
        # A richer extraction is done via tree-sitter in Phase 3+
        symbol = path.stem
        kind = _infer_kind(source, symbol)
        units.append(PaymentUnit(
            file=str(path),
            symbol=symbol,
            start_line=1,
            end_line=len(lines),
            kind=kind,
            imports=[],
            callees=[],
            source=source,
        ))
        return units
    except Exception:
        return []


_ALLOWED_SUFFIXES = {".py", ".js", ".ts", ".mjs", ".cjs"}
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".next", "dist", "build", ".venv", "venv"}


def discover_payment_units(repo_path: str | Path) -> list[PaymentUnit]:
    """Walk a repository and return all payment-relevant code units."""
    root = Path(repo_path)
    units: list[PaymentUnit] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(skip in path.parts for skip in _SKIP_DIRS):
            continue
        if path.suffix not in _ALLOWED_SUFFIXES:
            continue

        if path.suffix == ".py":
            units.extend(_discover_python(path))
        elif path.suffix in {".js", ".ts", ".mjs", ".cjs"}:
            units.extend(_discover_js(path))

    return units
