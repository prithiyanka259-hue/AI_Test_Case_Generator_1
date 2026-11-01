"""Run approved generated tests in a temporary, time-limited subprocess."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from analyzer import analyze_source
from validator import validate_source, validate_test_code

DEFAULT_TIMEOUT_SECONDS = 8
MAX_TIMEOUT_SECONDS = 15


def _parse_junit(path: Path) -> tuple[list[dict[str, str]], str | None]:
    if not path.exists():
        return [], None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [], f"Could not parse pytest's JUnit report: {exc}"
    results: list[dict[str, str]] = []
    for case in root.iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        outcome = "FAIL" if failure is not None or error is not None else "SKIP" if skipped is not None else "PASS"
        detail = ""
        report_node = failure if failure is not None else error if error is not None else skipped
        if report_node is not None:
            detail = (report_node.get("message") or report_node.text or "").strip()
        results.append(
            {
                "name": f"{case.get('classname', '')}.{case.get('name', '')}".strip("."),
                "outcome": outcome,
                "detail": detail,
            }
        )
    return results, None


def _coverage_percentage(temp_path: Path) -> tuple[float | None, str | None]:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "coverage",
            "json",
            f"--data-file={temp_path / '.coverage'}",
            "-o",
            str(temp_path / "coverage.json"),
            "--include=subject_module.py",
        ],
        cwd=temp_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        env=_runner_environment(),
    )
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip() or "Coverage report was unavailable."
    try:
        data = json.loads((temp_path / "coverage.json").read_text(encoding="utf-8"))
        files = data.get("files", {})
        source_file = next((value for name, value in files.items() if name.endswith("subject_module.py")), None)
        if source_file is None:
            return None, "Coverage could not find the analyzed source module."
        return float(source_file["summary"]["percent_covered"]), None
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        return None, f"Could not read the coverage summary: {exc}"


def _runner_environment() -> dict[str, str]:
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return environment


def run_tests(
    source: str,
    test_code: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Validate and execute tests in an isolated temporary directory."""
    source_validation = validate_source(source)
    if not source_validation.valid:
        return {
            "executed": False,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "coverage_percent": None,
            "timed_out": False,
            "execution_error": "Execution blocked because source validation failed.",
            "validation_errors": source_validation.errors,
            "test_results": [],
            "output": "",
        }
    analysis = analyze_source(source)
    test_validation = validate_test_code(test_code, {function.name for function in analysis.functions})
    if not test_validation.valid:
        return {
            "executed": False,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "coverage_percent": None,
            "timed_out": False,
            "execution_error": "Execution blocked because test validation failed.",
            "validation_errors": test_validation.errors,
            "test_results": [],
            "output": "",
        }

    if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"Timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds.")

    imports = ", ".join(function.name for function in analysis.functions)
    runnable_tests = f"from subject_module import {imports}\n\n{test_code}"

    with tempfile.TemporaryDirectory(prefix="ai_test_generator_") as temporary_directory:
        temp_path = Path(temporary_directory)
        source_path = temp_path / "subject_module.py"
        test_path = temp_path / "test_generated.py"
        junit_path = temp_path / "results.xml"
        source_path.write_text(source, encoding="utf-8")
        test_path.write_text(runnable_tests, encoding="utf-8")

        command = [
            sys.executable,
            "-I",
            "-m",
            "coverage",
            "run",
            "--branch",
            f"--data-file={temp_path / '.coverage'}",
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            f"--junitxml={junit_path}",
            str(test_path),
        ]
        timed_out = False
        process_error = None
        try:
            completed = subprocess.run(
                command,
                cwd=temp_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=_runner_environment(),
            )
            output = (completed.stdout + completed.stderr).strip()
            return_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            output = ""
            if exc.stdout:
                output += exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
            if exc.stderr:
                output += exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
            return_code = -1
            process_error = f"Test run exceeded the {timeout_seconds}-second time limit."
        except OSError as exc:
            output = ""
            return_code = -1
            process_error = f"Could not start the test subprocess: {exc}"

        test_results, junit_error = _parse_junit(junit_path)
        coverage_percent = None
        coverage_error = None
        if not timed_out and junit_path.exists():
            coverage_percent, coverage_error = _coverage_percentage(temp_path)
        failures = sum(result["outcome"] == "FAIL" for result in test_results)
        passed = sum(result["outcome"] == "PASS" for result in test_results)
        skipped = sum(result["outcome"] == "SKIP" for result in test_results)
        execution_error = process_error or junit_error
        if return_code not in (0, 1, 5) and execution_error is None:
            execution_error = f"Pytest/coverage runner exited with code {return_code}."
        return {
            "executed": not timed_out and (bool(test_results) or return_code in (0, 1)),
            "total": len(test_results),
            "passed": passed,
            "failed": failures,
            "skipped": skipped,
            "coverage_percent": coverage_percent,
            "coverage_error": coverage_error,
            "timed_out": timed_out,
            "execution_error": execution_error,
            "validation_errors": [],
            "test_results": test_results,
            "output": output,
        }
