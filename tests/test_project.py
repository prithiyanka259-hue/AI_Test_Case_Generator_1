from analyzer import analyze_source
from generator import generate_test_cases
from test_runner import run_tests
from validator import validate_source, validate_test_code


def test_analyzer_extracts_function_and_exception():
    analysis = analyze_source(
        "def divide(numerator: int, denominator: int) -> float:\n"
        "    if denominator == 0:\n"
        "        raise ValueError('zero')\n"
        "    return numerator / denominator\n"
    )
    assert analysis.functions[0].name == "divide"
    assert [parameter.name for parameter in analysis.functions[0].parameters] == [
        "numerator",
        "denominator",
    ]
    assert "ValueError" in analysis.functions[0].possible_exceptions
    assert "ZeroDivisionError (possible)" in analysis.functions[0].possible_exceptions


def test_source_validator_rejects_imports_and_attributes():
    unsafe_import = validate_source("import os\ndef f():\n    return 1\n")
    unsafe_attribute = validate_source("def f():\n    return (1).__class__\n")
    assert not unsafe_import.valid
    assert not unsafe_attribute.valid


def test_source_validator_rejects_recursive_calls_and_computed_defaults():
    recursive = validate_source("def recurse(n: int):\n    return recurse(n)\n")
    computed_default = validate_source("def f(value=1 + 2):\n    return value\n")
    assert not recursive.valid
    assert not computed_default.valid


def test_source_validator_accepts_starter_example_fstring():
    validation = validate_source(
        "def greet(name: str = 'friend') -> str:\n"
        "    return f'Hello, {name}!'\n"
    )
    assert validation.valid, validation.errors


def test_source_validator_allows_isinstance_but_keeps_other_builtins_blocked():
    type_check = validate_source(
        "def greet(name: str):\n"
        "    if not isinstance(name, str):\n"
        "        raise TypeError('name must be a string')\n"
        "    return name\n"
    )
    unsafe_builtin = validate_source(
        "def read(path: str):\n"
        "    return open(path)\n"
    )
    assert type_check.valid, type_check.errors
    assert not unsafe_builtin.valid
    assert any("Call to 'open' is not allowed" in error for error in unsafe_builtin.errors)


def test_generated_tests_pass_for_isinstance_type_check():
    source = (
        "def greet(name: str = 'friend') -> str:\n"
        "    if not isinstance(name, str):\n"
        "        raise TypeError('Name must be a string')\n"
        "    return f'Hello, {name}!'\n"
    )
    generated = generate_test_cases(source, analyze_source(source))
    result = run_tests(source, generated.test_code)
    assert result["executed"], result["validation_errors"]
    assert result["total"] == len(generated.cases)
    assert result["failed"] == 0, result["test_results"]


def test_generator_produces_multiple_categories_and_valid_tests():
    source = "def divide(a: int, b: int) -> float:\n    return a / b\n"
    analysis = analyze_source(source)
    generated = generate_test_cases(source, analysis)
    validation = validate_test_code(generated.test_code, {"divide"})
    categories = {case["category"] for case in generated.cases}
    assert {"normal", "boundary", "invalid input", "exception", "regression"} <= categories
    assert validation.valid, validation.errors


def test_ai_generation_falls_back_when_api_key_is_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    generated = generate_test_cases(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        use_ai=True,
    )
    assert generated.provider == "rule-based"
    assert generated.cases
    assert generated.warnings


def test_generator_uses_explicit_guard_exception_for_boundary():
    source = (
        "def divide(a: float, b: float) -> float:\n"
        "    if b == 0:\n"
        "        raise ValueError('b must not be zero')\n"
        "    return a / b\n"
    )
    analysis = analyze_source(source)
    generated = generate_test_cases(source, analysis)
    result = run_tests(source, generated.test_code)
    boundary_exception = next(
        case for case in result["test_results"]
        if "b_boundary_exception" in case["name"]
    )
    assert boundary_exception["outcome"] == "PASS", boundary_exception["detail"]


def test_duplicate_test_bodies_are_reported():
    tests = "def test_one():\n    add(1, 2)\n\ndef test_two():\n    add(1, 2)\n"
    validation = validate_test_code(tests, {"add"})
    assert not validation.valid
    assert validation.duplicates


def test_runner_executes_approved_test_and_reports_coverage():
    source = "def add(a: int, b: int) -> int:\n    return a + b\n"
    tests = "def test_add():\n    assert add(2, 3) == 5\n"
    result = run_tests(source, tests)
    assert result["executed"]
    assert result["total"] == 1
    assert result["passed"] == 1
    assert result["failed"] == 0
    assert result["coverage_percent"] is not None


def test_runner_blocks_unsafe_test_code():
    result = run_tests(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        "import os\ndef test_unsafe():\n    add(1, 2)\n",
    )
    assert not result["executed"]
    assert result["validation_errors"]


def test_runner_reports_invalid_source_without_raising():
    result = run_tests("def broken(:\n    pass\n", "def test_broken():\n    assert True\n")
    assert not result["executed"]
    assert result["validation_errors"]
