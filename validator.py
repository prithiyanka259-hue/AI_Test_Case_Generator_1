"""Syntax, duplication, and conservative AST policy checks."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from analyzer import MAX_AST_NODES, MAX_SOURCE_CHARS

SAFE_BUILTINS = {
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "float",
    "int",
    "isinstance",
    "len",
    "list",
    "max",
    "min",
    "round",
    "str",
    "sum",
    "tuple",
}
SAFE_EXCEPTIONS = {
    "AssertionError",
    "IndexError",
    "KeyError",
    "TypeError",
    "ValueError",
    "ZeroDivisionError",
}

_SOURCE_NODES = {
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign,
    ast.AnnAssign, ast.Expr, ast.If, ast.Try, ast.ExceptHandler, ast.Raise,
    ast.Pass, ast.Call, ast.keyword, ast.Name, ast.Load, ast.Store, ast.Constant,
    ast.JoinedStr, ast.FormattedValue,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice, ast.IfExp,
    ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.UAdd, ast.USub,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Is, ast.IsNot, ast.In, ast.NotIn,
}

_TEST_NODES = {
    ast.Module, ast.FunctionDef, ast.arguments, ast.Expr, ast.Assign,
    ast.AnnAssign, ast.Assert, ast.Try, ast.ExceptHandler, ast.Pass,
    ast.Call, ast.keyword, ast.Name, ast.Load, ast.Store, ast.Constant,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice,
    ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.UAdd, ast.USub,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Is, ast.IsNot, ast.In, ast.NotIn,
}


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str]
    duplicates: list[str]

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "duplicates": self.duplicates,
        }


def _parse(code: str, label: str) -> tuple[ast.Module | None, list[str]]:
    if not code.strip():
        return None, [f"{label} is empty."]
    if len(code) > MAX_SOURCE_CHARS:
        return None, [f"{label} exceeds the {MAX_SOURCE_CHARS:,}-character limit."]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return None, [f"Syntax error on line {exc.lineno}: {exc.msg}"]
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        return None, [f"{label} exceeds the {MAX_AST_NODES:,}-node limit."]
    return tree, []


def validate_source(source: str) -> ValidationResult:
    """Validate source syntax and reject constructs outside the execution subset."""
    tree, errors = _parse(source, "Source code")
    if tree is None:
        return ValidationResult(False, errors, [])

    function_names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    if not function_names:
        errors.append("Define at least one top-level synchronous function.")
    if len(function_names) != sum(isinstance(node, ast.FunctionDef) for node in tree.body):
        errors.append("Function names must be unique.")

    call_graph: dict[str, set[str]] = {}
    for function in (node for node in tree.body if isinstance(node, ast.FunctionDef)):
        call_graph[function.name] = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in function_names
        }
        for default in [*function.args.defaults, *(value for value in function.args.kw_defaults if value is not None)]:
            try:
                ast.literal_eval(default)
            except (ValueError, TypeError, SyntaxError, RecursionError):
                errors.append(
                    f"Function defaults must be literal values (function '{function.name}', line {default.lineno})."
                )
    pending = [name for name, calls in call_graph.items() if not calls]
    acyclic = set(pending)
    while pending:
        completed_name = pending.pop()
        for name, calls in call_graph.items():
            if name not in acyclic and completed_name in calls:
                calls.discard(completed_name)
                if not calls:
                    acyclic.add(name)
                    pending.append(name)
    if len(acyclic) != len(call_graph):
        errors.append("Recursive function-call cycles are not allowed.")

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if not isinstance(node, ast.FunctionDef):
            errors.append(f"Only function definitions and module docstrings are allowed (line {node.lineno}).")
            continue
        if node.decorator_list:
            errors.append(f"Decorators are not allowed (function '{node.name}', line {node.lineno}).")

    for node in ast.walk(tree):
        if type(node) not in _SOURCE_NODES:
            errors.append(f"Unsupported source construct '{type(node).__name__}' on line {getattr(node, 'lineno', 1)}.")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, int) and node.value.bit_length() > 256:
                errors.append(f"Integer literals are limited to 256 bits (line {node.lineno}).")
            elif isinstance(node.value, str) and len(node.value) > 10_000:
                errors.append(f"String literals are limited to 10,000 characters (line {node.lineno}).")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            errors.append(f"Names beginning with '__' are not allowed (line {node.lineno}).")
        if isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            errors.append(f"Custom f-string format specifications are not allowed (line {node.lineno}).")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                errors.append(f"Only direct function calls are allowed (line {node.lineno}).")
            elif node.func.id not in function_names | SAFE_BUILTINS | SAFE_EXCEPTIONS:
                errors.append(f"Call to '{node.func.id}' is not allowed (line {node.lineno}).")
        if isinstance(node, ast.ExceptHandler):
            if node.type is not None:
                names = [node.type.id] if isinstance(node.type, ast.Name) else [
                    item.id for item in node.type.elts if isinstance(item, ast.Name)
                ] if isinstance(node.type, ast.Tuple) else []
                if not names or any(name not in SAFE_EXCEPTIONS | {"Exception"} for name in names):
                    errors.append(f"Only approved exception types may be caught (line {node.lineno}).")

    errors = list(dict.fromkeys(errors))
    return ValidationResult(not errors, errors, [])


def validate_test_code(test_code: str, function_names: set[str]) -> ValidationResult:
    """Validate generated tests before they are saved or executed."""
    tree, errors = _parse(test_code, "Generated tests")
    if tree is None:
        return ValidationResult(False, errors, [])

    test_functions: list[ast.FunctionDef] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            errors.append(f"Only test function definitions are allowed (line {node.lineno}).")
            continue
        test_functions.append(node)
        if not node.name.startswith("test_"):
            errors.append(f"Test function '{node.name}' must start with 'test_'.")
        if node.args.args or node.args.posonlyargs or node.args.kwonlyargs or node.args.vararg or node.args.kwarg:
            errors.append(f"Test function '{node.name}' must not take arguments.")
        if node.decorator_list:
            errors.append(f"Decorators are not allowed (test '{node.name}').")
    if not test_functions:
        errors.append("At least one test function is required.")

    seen_names: set[str] = set()
    duplicates: list[str] = []
    seen_bodies: set[str] = set()
    for node in test_functions:
        if node.name in seen_names:
            duplicates.append(node.name)
        seen_names.add(node.name)
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
        if body in seen_bodies:
            duplicates.append(f"{node.name} (duplicate test body)")
        seen_bodies.add(body)

    for node in ast.walk(tree):
        if type(node) not in _TEST_NODES:
            errors.append(f"Unsupported test construct '{type(node).__name__}' on line {getattr(node, 'lineno', 1)}.")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, int) and node.value.bit_length() > 256:
                errors.append(f"Integer literals are limited to 256 bits (line {node.lineno}).")
            elif isinstance(node.value, str) and len(node.value) > 10_000:
                errors.append(f"String literals are limited to 10,000 characters (line {node.lineno}).")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            errors.append(f"Names beginning with '__' are not allowed (line {node.lineno}).")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in function_names:
                errors.append(f"Tests may call only analyzed functions directly (line {node.lineno}).")
        if isinstance(node, ast.ExceptHandler):
            if node.type is not None and not (
                isinstance(node.type, ast.Name)
                and node.type.id in SAFE_EXCEPTIONS | {"Exception"}
            ):
                errors.append(f"Only approved exception types may be caught in tests (line {node.lineno}).")

    errors = list(dict.fromkeys(errors))
    duplicates = list(dict.fromkeys(duplicates))
    if duplicates:
        errors.append("Duplicate test cases were found: " + ", ".join(duplicates))
    return ValidationResult(not errors, errors, duplicates)
