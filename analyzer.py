"""Static analysis helpers for the test-case generator."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass

MAX_SOURCE_CHARS = 30_000
MAX_AST_NODES = 2_500


@dataclass(frozen=True)
class ParameterInfo:
    name: str
    kind: str
    annotation: str | None
    default: str | None
    required: bool


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    parameters: list[ParameterInfo]
    return_expressions: list[str]
    possible_exceptions: list[str]


@dataclass(frozen=True)
class AnalysisResult:
    functions: list[FunctionInfo]
    possible_exceptions: list[str]
    notes: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _literal_text(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return None


def _parameter_info(args: ast.arguments) -> list[ParameterInfo]:
    result: list[ParameterInfo] = []
    positional = [*args.posonlyargs, *args.args]
    defaults_start = len(positional) - len(args.defaults)
    for index, parameter in enumerate(positional):
        default = args.defaults[index - defaults_start] if index >= defaults_start else None
        kind = "positional-only" if index < len(args.posonlyargs) else "positional"
        result.append(
            ParameterInfo(
                name=parameter.arg,
                kind=kind,
                annotation=_literal_text(parameter.annotation),
                default=_literal_text(default),
                required=default is None,
            )
        )
    if args.vararg:
        result.append(
            ParameterInfo(args.vararg.arg, "variadic positional", _literal_text(args.vararg.annotation), None, False)
        )
    for parameter, default in zip(args.kwonlyargs, args.kw_defaults):
        result.append(
            ParameterInfo(
                name=parameter.arg,
                kind="keyword-only",
                annotation=_literal_text(parameter.annotation),
                default=_literal_text(default),
                required=default is None,
            )
        )
    if args.kwarg:
        result.append(
            ParameterInfo(args.kwarg.arg, "variadic keyword", _literal_text(args.kwarg.annotation), None, False)
        )
    return result


def analyze_source(source: str) -> AnalysisResult:
    """Return function signatures and statically visible exception indicators."""
    if len(source) > MAX_SOURCE_CHARS:
        raise ValueError(f"Source code exceeds the {MAX_SOURCE_CHARS:,}-character limit.")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"Python syntax error on line {exc.lineno}: {exc.msg}") from exc

    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ValueError(f"Source code exceeds the {MAX_AST_NODES:,}-node analysis limit.")

    functions: list[FunctionInfo] = []
    all_exceptions: set[str] = set()
    notes = [
        "Analysis is static: return expressions and exception indicators are inferred from syntax, not executed."
    ]

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.AsyncFunctionDef):
            notes.append(f"Async function '{node.name}' is listed but not supported by the test generator.")
            continue

        exceptions: set[str] = set()
        returns: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                expression = _literal_text(child.value)
                if expression is not None:
                    returns.append(expression)
            elif isinstance(child, ast.Raise) and child.exc is not None:
                exception = child.exc.func if isinstance(child.exc, ast.Call) else child.exc
                if isinstance(exception, ast.Name):
                    exceptions.add(exception.id)
            elif isinstance(child, ast.BinOp) and isinstance(
                child.op, (ast.Div, ast.FloorDiv, ast.Mod)
            ):
                exceptions.add("ZeroDivisionError (possible)")
            elif isinstance(child, ast.Subscript):
                exceptions.add("IndexError or KeyError (possible)")
            elif isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                if child.func.id in {"int", "float"}:
                    exceptions.add("ValueError (possible)")

        all_exceptions.update(exceptions)
        functions.append(
            FunctionInfo(
                name=node.name,
                parameters=_parameter_info(node.args),
                return_expressions=returns,
                possible_exceptions=sorted(exceptions),
            )
        )

    if not functions:
        notes.append("No top-level synchronous functions were found.")
    return AnalysisResult(
        functions=functions,
        possible_exceptions=sorted(all_exceptions),
        notes=notes,
    )
