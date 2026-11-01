# Automated Test Case Generation Using AI

A beginner-friendly Streamlit mini project that analyzes Python functions, generates candidate tests, validates them, runs them with pytest, and reports coverage.

## Features

- AST-based function, parameter, return-expression, and possible-exception analysis.
- Local rule-based generation for normal, boundary, invalid-input, exception, and regression cases.
- Optional OpenAI Chat Completions adapter. The app uses the local generator unless the user checks the explicit opt-in box.
- Syntax, duplicate-body, and conservative AST validation before tests can be run.
- Pytest execution in a temporary directory, using Python isolated mode, a restricted environment, disabled third-party pytest plugin autoload, and a timeout.
- JUnit-based individual PASS/FAIL/SKIP results, source-module coverage, and a downloadable JSON report.
- Downloadable generated tests, also saved under `generated_tests/`.

## Requirements

- Python 3.10 or later
- VS Code with the Python extension
- Internet access only if you choose to use OpenAI

## Install and run

Open this folder in VS Code. In the integrated terminal, create and activate a virtual environment:

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Streamlit opens the application in a browser. Paste top-level Python function definitions or start with the example already in the editor, then select **Generate Test Cases** and **Run Tests**.

## Optional OpenAI generation

Set `OPENAI_API_KEY` in the terminal environment before launching Streamlit. The model defaults to `gpt-4o-mini`; override it with `OPENAI_MODEL` if needed. The source is not sent to OpenAI unless the user explicitly checks the opt-in box. If the request fails, the app displays a warning and falls back to local rules.

PowerShell example:

```powershell
$env:OPENAI_API_KEY = "your-key"
streamlit run app.py
```

Do not put API keys in the source files or commit them.

## Run the project's checks

```powershell
python -m pytest -q
```

## Execution safety and limitations

The app accepts a deliberately small source subset: top-level synchronous functions, simple expressions, conditionals, assignments, and exception handling. It rejects imports, attribute access, classes, decorators, loops, file/network access, and unapproved calls. Generated tests are validated separately. Approved code runs only in a temporary subprocess with isolated Python mode, a short timeout, and a reduced environment; temporary files are removed after the run.

These controls reduce risk for a local college demo but are **not a hardened OS sandbox** and do not guarantee containment of hostile code or resource exhaustion. Do not execute untrusted or sensitive code. For genuinely hostile submissions, run the app inside a disposable, resource-limited OS container/VM with no network and an unprivileged user.

Static analysis cannot know the correct output for every function. Rule-generated normal and boundary tests are smoke tests; invalid and exception cases assert that an exception occurs for the selected input, and regression cases check repeat-call determinism. Review generated tests and interpret failures against the function's intended behavior.
