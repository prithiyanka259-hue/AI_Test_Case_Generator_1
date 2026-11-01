"""Streamlit interface for automated Python test generation."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from analyzer import analyze_source
from generator import generate_test_cases
from test_runner import run_tests
from validator import validate_source, validate_test_code

PROJECT_ROOT = Path(__file__).resolve().parent
GENERATED_DIR = PROJECT_ROOT / "generated_tests"
SAMPLE_CODE = '''def divide(a: float, b: float) -> float:
    """Divide two numbers."""
    if b == 0:
        raise ValueError("b must not be zero")
    return a / b


def greet(name: str = "friend") -> str:
    if not isinstance(name, str):
        raise TypeError("Name must be a string")
    return f"Hello, {name}!"
'''

st.set_page_config(page_title="AI Test Case Generator", page_icon="🧪", layout="wide")
st.title("🧪 Automated Test Case Generation Using AI")
st.caption("Analyze Python functions, generate candidate tests, validate them, and run them with pytest.")

with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. Paste Python functions.\n"
        "2. Generate tests locally or opt in to OpenAI.\n"
        "3. Review validation, then run with pytest.\n"
        "4. Download the tests and execution report."
    )
    st.warning(
        "Execution is restricted to a conservative Python subset and a timed temporary subprocess. "
        "This is a college-project safeguard, not a hardened security sandbox. Do not submit sensitive "
        "or hostile code. OpenAI use sends source code to the provider only when you explicitly opt in."
    )
    api_key_available = bool(os.environ.get("OPENAI_API_KEY"))
    use_ai = st.checkbox(
        "Send source code to OpenAI for test generation",
        value=False,
        disabled=not api_key_available,
        help="Requires OPENAI_API_KEY in the environment. The local rule-based generator is always available.",
    )
    if not api_key_available:
        st.caption("No OPENAI_API_KEY detected; local rule-based generation is available.")

source_code = st.text_area(
    "Python source code",
    value=SAMPLE_CODE,
    height=280,
    placeholder="def add(a: int, b: int) -> int:\n    return a + b",
)

generate_col, run_col = st.columns(2)
with generate_col:
    generate_clicked = st.button("✨ Generate Test Cases", type="primary", use_container_width=True)
with run_col:
    run_clicked = st.button("▶ Run Tests", use_container_width=True)

if generate_clicked:
    source_check = validate_source(source_code)
    if not source_check.valid:
        st.session_state.pop("generated_test_code", None)
        st.error("Source validation failed. Update the source and try again.")
        for error in source_check.errors:
            st.write(f"- {error}")
    else:
        analysis = analyze_source(source_code)
        generation = generate_test_cases(source_code, analysis, use_ai=use_ai)
        test_check = validate_test_code(
            generation.test_code,
            {function.name for function in analysis.functions},
        )
        if not test_check.valid:
            st.session_state.pop("generated_test_code", None)
            st.error("Generated tests did not pass validation.")
            for error in test_check.errors:
                st.write(f"- {error}")
        else:
            GENERATED_DIR.mkdir(exist_ok=True)
            filename = "tests_" + hashlib.sha256(source_code.encode("utf-8")).hexdigest()[:10] + ".py"
            saved_path = GENERATED_DIR / filename
            saved_path.write_text(generation.test_code, encoding="utf-8")
            st.session_state["generated_test_code"] = generation.test_code
            st.session_state["generated_source_code"] = source_code
            st.session_state["generation_provider"] = generation.provider
            st.session_state["generation_cases"] = generation.cases
            st.session_state["analysis"] = analysis.to_dict()
            st.session_state["validation"] = test_check.to_dict()
            st.session_state["generated_filename"] = filename
            st.session_state.pop("execution_result", None)
            st.success(f"Generated and validated {len(generation.cases)} test case(s) using {generation.provider}.")
            for warning in generation.warnings:
                st.warning(warning)

if "generated_test_code" in st.session_state:
    st.subheader("Generated test cases")
    st.caption(f"Saved as generated_tests/{st.session_state['generated_filename']}")
    st.code(st.session_state["generated_test_code"], language="python")
    with st.expander("Code analysis"):
        st.json(st.session_state["analysis"])
    with st.expander("Validation"):
        validation = st.session_state["validation"]
        if validation["valid"]:
            st.success("Syntax, allowed constructs, and duplicate checks passed.")
        else:
            st.error("\n".join(validation["errors"]))
        if st.session_state["generation_cases"]:
            st.dataframe(st.session_state["generation_cases"], use_container_width=True, hide_index=True)
    st.download_button(
    "⬇ Download generated test file",
    data=st.session_state["generated_test_code"],
    file_name=st.session_state["generated_filename"],
    mime="text/x-python",
)

if run_clicked:
    generated = st.session_state.get("generated_test_code")
    generated_source = st.session_state.get("generated_source_code")

    if not generated:
        st.error("Generate test cases before running them.")

    elif generated_source != source_code:
        st.error("The source changed after generation. Generate tests again.")

    else:
        with st.spinner("Running tests..."):
            execution = run_tests(source_code, generated)

        st.session_state["execution_result"] = execution


if "execution_result" in st.session_state:
    execution = st.session_state["execution_result"]

    st.subheader("Test results")

    metric_columns = st.columns(5)

    metric_columns[0].metric("Total", execution["total"])
    metric_columns[1].metric("Passed", execution["passed"])
    metric_columns[2].metric("Failed", execution["failed"])

    metric_columns[3].metric(
        "Coverage",
        f'{execution["coverage_percent"]:.1f}%'
        if execution["coverage_percent"] is not None
        else "N/A"
    )

    metric_columns[4].metric("Skipped", execution["skipped"])

    if execution["timed_out"]:
        st.error(execution["execution_error"])

    elif execution["failed"] == 0 and execution["executed"]:
        st.success("Test run completed successfully.")

    elif execution["execution_error"]:
        st.error(execution["execution_error"])

    else:
        st.warning("Test run completed with failing test cases.")

    if execution.get("coverage_error"):
        st.info(
            f'Coverage unavailable: {execution["coverage_error"]}'
        )

    if execution.get("test_results"):
        st.dataframe(
            execution["test_results"],
            use_container_width=True,
            hide_index=True
        )

    with st.expander("Pytest output"):
        st.code(
            execution["output"] or "No console output was captured.",
            language="text"
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": st.session_state.get("generation_provider"),
        "analysis": st.session_state.get("analysis"),
        "validation": st.session_state.get("validation"),
        "execution": execution,
    }

    st.download_button(
        "⬇ Download test report (JSON)",
        data=json.dumps(report, indent=2, ensure_ascii=False),
        file_name="test_report.json",
        mime="application/json",
    )
