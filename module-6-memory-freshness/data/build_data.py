"""Build this module's data: a small fabricated project with a real git history,
the CI failures it had, and the triage sessions that remembered how to fix them.

    python3 build_data.py

It creates, next to this file:
    repo/        invoicekit, a fictional invoicing library, with two tags: old and new
    ci_logs/     failing CI builds at the old tag
    sessions/    five triage sessions, which hold the fourteen memories
    memories.jsonl     the memory records from those sessions
    eval/questions.json  fourteen new failures at the new tag, with the expected memory and verdict

Commits use fixed names and dates, so the commit SHAs are the same every time.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE / "repo"
REPO_NAME = "invoicekit"

# ---------------------------------------------------------------- the code at the old tag

OLD_FILES = {
    ".github/workflows/ci.yml": """name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    continue-on-error: ${{ matrix.python-version == '3.9' }}
    strategy:
      matrix:
        python-version: ["3.9", "3.10", "3.11", "3.12"]
    env:
      TZ: UTC
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -r requirements-dev.txt
      - run: pip install -e .
      - run: pytest -p no:randomly --maxfail=5
""",
    "requirements-dev.txt": """pytest==8.3.3
pytest-randomly==3.15.0
freezegun==1.5.1
""",
    "pyproject.toml": """[project]
name = "invoicekit"
version = "1.0.0"
requires-python = ">=3.9"

[tool.setuptools.packages.find]
where = ["src"]
""",
    "src/invoicekit/__init__.py": '"""A small invoicing library."""\n',
    "src/invoicekit/invoice.py": """from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Line:
    description: str
    amount: Decimal
    customer_ref: str | None = None


@dataclass
class Invoice:
    number: str
    lines: list[Line] = field(default_factory=list)

    def total(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal("0"))
""",
    "src/invoicekit/export.py": """import csv


def export_csv(invoice, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["description", "amount"])
        for line in invoice.lines:
            writer.writerow([line.description, str(line.amount)])
""",
    "src/invoicekit/discounts.py": """from decimal import Decimal


def apply_discount(lines, percent):
    # Changes the lines in place.
    for line in lines:
        line.amount = line.amount * (1 - Decimal(percent) / 100)
    return lines
""",
    "src/invoicekit/customers.py": """def vat_number(customer):
    if customer["type"] == "business":
        return customer["vat_number"]
    return None
""",
    "src/invoicekit/currency.py": """SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "KES"}


def check_currency(code):
    if code not in SUPPORTED_CURRENCIES:
        raise ValueError(f"unknown currency {code!r}")
    return code
""",
    "src/invoicekit/numbering.py": """_counter = 0


def next_number(prefix="INV"):
    global _counter
    _counter += 1
    return f"{prefix}-{_counter:04d}"
""",
    "src/invoicekit/dates.py": """from datetime import date, datetime, timedelta


def today():
    return datetime.now().date()


def due_date(issued: date, terms_days: int) -> date:
    due = issued + timedelta(days=terms_days)
    while due.weekday() >= 5:
        due += timedelta(days=1)
    return due
""",
    "src/invoicekit/tax.py": """from decimal import ROUND_HALF_EVEN, Decimal


def vat(amount: Decimal, rate: Decimal) -> Decimal:
    return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
""",
    "tests/conftest.py": """import pytest

from invoicekit import numbering


@pytest.fixture(autouse=True)
def reset_counter():
    numbering._counter = 0
    yield
""",
    "tests/test_invoice.py": """from decimal import Decimal

from invoicekit.invoice import Invoice, Line


def test_total():
    invoice = Invoice("INV-0001", [Line("a", Decimal("0.10")), Line("b", Decimal("0.20"))])
    assert invoice.total() == Decimal("0.30")
""",
    "tests/test_tax.py": """from decimal import Decimal

from invoicekit.tax import vat


def test_vat_rounding():
    assert vat(Decimal("10.25"), Decimal("0.20")) == Decimal("2.05")
""",
    "tests/test_dates.py": """from datetime import date

from invoicekit.dates import due_date, today


def test_due_date_skips_weekend():
    assert due_date(date(2026, 1, 2), 1) == date(2026, 1, 5)


def test_today_is_a_date():
    assert today() <= date.today()
""",
    "tests/test_misc.py": """from decimal import Decimal

import pytest

from invoicekit.currency import check_currency
from invoicekit.customers import vat_number
from invoicekit.discounts import apply_discount
from invoicekit.export import export_csv
from invoicekit.invoice import Invoice, Line
from invoicekit.numbering import next_number


def test_currency():
    with pytest.raises(ValueError):
        check_currency("EURO")


def test_numbering():
    assert next_number() == "INV-0001"


def test_discount_once():
    lines = [Line("a", Decimal("100"))]
    apply_discount(lines, 10)
    assert lines[0].amount == Decimal("90")


def test_business_vat():
    assert vat_number({"type": "business", "vat_number": "GB123"}) == "GB123"


def test_export(tmp_path):
    export_csv(Invoice("INV-0001", [Line("Café", Decimal("5"))]), tmp_path / "out.csv")
""",
}

# ---------------------------------------------------------------- the commits after the old tag

NEW_COMMITS = [
    ("Drop Python 3.9 and 3.10 from CI", {
        ".github/workflows/ci.yml": lambda text: text.replace(
            "    continue-on-error: ${{ matrix.python-version == '3.9' }}\n", ""
        ).replace('["3.9", "3.10", "3.11", "3.12"]', '["3.11", "3.12", "3.13"]'),
        "pyproject.toml": lambda text: text.replace('requires-python = ">=3.9"', 'requires-python = ">=3.11"'),
    }),
    ("Use timezone-aware dates", {
        "src/invoicekit/dates.py": lambda text: text.replace(
            "from datetime import date, datetime, timedelta", "from datetime import date, datetime, timedelta, timezone"
        ).replace("return datetime.now().date()", "return datetime.now(timezone.utc).date()"),
        ".github/workflows/ci.yml": lambda text: text.replace("    env:\n      TZ: UTC\n", ""),
    }),
    ("Round VAT half up, as tax authorities do", {
        "src/invoicekit/tax.py": lambda text: text.replace("ROUND_HALF_EVEN", "ROUND_HALF_UP"),
    }),
    ("Remove pytest-randomly", {
        "requirements-dev.txt": lambda text: text.replace("pytest-randomly==3.15.0\n", ""),
        ".github/workflows/ci.yml": lambda text: text.replace("pytest -p no:randomly --maxfail=5", "pytest --maxfail=5"),
    }),
    ("Add currency formatting", {
        "src/invoicekit/currency.py": lambda text: text + '''

def format_amount(amount, code):
    return f"{check_currency(code)} {amount:,.2f}"
''',
    }),
    ("Add an issue date fixture", {
        "tests/conftest.py": lambda text: text + '''

@pytest.fixture
def issue_date():
    from datetime import date

    return date(2026, 1, 5)
''',
    }),
]

# ---------------------------------------------------------------- the memories

# expected: what freshness verification should conclude at the new tag.
MEMORIES = [
    {"id": "m01", "session": "s1", "files": ["src/invoicekit/invoice.py"],
     "failure": "test_total fails: assert Decimal('0.30000000000000004') == Decimal('0.30')",
     "root_cause": "A test built line amounts from floats, so the total picked up float error.",
     "workaround": "Build amounts from strings, e.g. Decimal(\"0.10\"). Invoice.total already sums Decimals.",
     "evidence": 'return sum((line.amount for line in self.lines), Decimal("0"))',
     "last_used_session": 5, "expected": "valid"},
    {"id": "m02", "session": "s1", "files": ["src/invoicekit/export.py"],
     "failure": "test_export fails with UnicodeEncodeError: 'ascii' codec can't encode character 'é'",
     "root_cause": "A local patch opened the CSV without an encoding. export_csv writes UTF-8.",
     "workaround": "Keep encoding=\"utf-8\" when opening the export file.",
     "evidence": 'with open(path, "w", newline="", encoding="utf-8") as f:',
     "last_used_session": 4, "expected": "valid"},
    {"id": "m03", "session": "s2", "files": ["src/invoicekit/discounts.py", "tests/test_misc.py"],
     "failure": "test_discount_once fails: assert Decimal('81.00') == Decimal('90')",
     "root_cause": "apply_discount changes the lines in place, so calling it twice applies the discount twice.",
     "workaround": "Call apply_discount once, or on a copy of the lines.",
     "evidence": "line.amount = line.amount * (1 - Decimal(percent) / 100)",
     "last_used_session": 3, "expected": "valid"},
    {"id": "m04", "session": "s2", "files": ["src/invoicekit/customers.py"],
     "failure": "test_business_vat fails with KeyError: 'vat_number'",
     "root_cause": "Business customers must have a vat_number key. Fixtures for business customers left it out.",
     "workaround": "Add vat_number to business customer fixtures, even if it's None.",
     "evidence": 'return customer["vat_number"]',
     "last_used_session": 5, "expected": "valid"},
    {"id": "m05", "session": "s3", "files": ["src/invoicekit/currency.py"],
     "failure": "test_currency fails with ValueError: unknown currency 'EURO'",
     "root_cause": "Only the codes in SUPPORTED_CURRENCIES are accepted, and EURO isn't an ISO code.",
     "workaround": "Use the three-letter code, EUR.",
     "evidence": 'SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "KES"}',
     "last_used_session": 4, "expected": "refreshed"},
    {"id": "m06", "session": "s3", "files": ["tests/conftest.py", "src/invoicekit/numbering.py"],
     "failure": "test_numbering fails: assert 'INV-0003' == 'INV-0001'",
     "root_cause": "The invoice counter is module-level, so numbers carry over between tests.",
     "workaround": "Keep the autouse reset_counter fixture in tests/conftest.py.",
     "evidence": "def reset_counter():",
     "last_used_session": 5, "expected": "refreshed"},
    {"id": "m07", "session": "s4", "files": [".github/workflows/ci.yml"],
     "failure": "ModuleNotFoundError: No module named 'invoicekit'",
     "root_cause": "The package lives under src/, so CI has to install it before running the tests.",
     "workaround": "Keep the `pip install -e .` step in the CI workflow.",
     "evidence": "- run: pip install -e .",
     "last_used_session": 4, "expected": "refreshed"},
    {"id": "m08", "session": "s4", "files": ["src/invoicekit/dates.py"],
     "failure": "test_due_date_skips_weekend fails: assert datetime.date(2026, 1, 3) == datetime.date(2026, 1, 5)",
     "root_cause": "due_date moves a due date that falls on a weekend to the next Monday. A local patch removed that loop.",
     "workaround": "Keep the weekday loop in due_date.",
     "evidence": "while due.weekday() >= 5:",
     "last_used_session": 4, "expected": "refreshed"},
    {"id": "m09", "session": "s5", "files": [".github/workflows/ci.yml", "src/invoicekit/invoice.py"],
     "failure": "The Python 3.9 job fails: TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'",
     "root_cause": "invoice.py uses `str | None`, which Python 3.9 can't evaluate.",
     "workaround": "Ignore it: the 3.9 job is allowed to fail with continue-on-error in the CI workflow.",
     "evidence": "continue-on-error: ${{ matrix.python-version == '3.9' }}",
     "last_used_session": 5, "expected": "stale"},
    {"id": "m10", "session": "s5", "files": [".github/workflows/ci.yml", "src/invoicekit/dates.py"],
     "failure": "test_today_is_a_date fails around midnight: assert datetime.date(2026, 3, 2) <= datetime.date(2026, 3, 1)",
     "root_cause": "today() uses the machine's local time, which differs from the date the test expects.",
     "workaround": "CI sets TZ: UTC in the workflow env. Set TZ=UTC locally too.",
     "evidence": "TZ: UTC",
     "last_used_session": 5, "expected": "stale"},
    {"id": "m11", "session": "s5", "files": ["src/invoicekit/tax.py", "tests/test_tax.py"],
     "failure": "test_vat_rounding fails: assert Decimal('2.05') == Decimal('2.06')",
     "root_cause": "vat rounds half to even, so 2.050 becomes 2.05, not 2.06.",
     "workaround": "Expect half-to-even results in tests: vat uses ROUND_HALF_EVEN.",
     "evidence": "rounding=ROUND_HALF_EVEN",
     "last_used_session": 5, "expected": "stale"},
    {"id": "m12", "session": "s4", "files": [".github/workflows/ci.yml", "requirements-dev.txt"],
     "failure": "Tests pass alone but fail together in a different order each run",
     "root_cause": "pytest-randomly shuffles the test order, and some tests share state.",
     "workaround": "CI runs pytest with -p no:randomly to keep a fixed order.",
     "evidence": "pytest -p no:randomly",
     "last_used_session": 5, "expected": "stale"},
    # Never used again after the session that wrote them, so they expire.
    {"id": "m13", "session": "s1", "files": ["src/invoicekit/invoice.py"],
     "failure": "TypeError: Line.__init__() missing 1 required positional argument: 'amount'",
     "root_cause": "A Line needs a description and an amount. Only customer_ref is optional.",
     "workaround": "Pass both the description and the amount when building a Line.",
     "evidence": "amount: Decimal",
     "last_used_session": 1, "expected": "expired"},
    {"id": "m14", "session": "s1", "files": ["src/invoicekit/export.py"],
     "failure": "test_export_header fails: assert ['description', 'amount'] == ['Description', 'Amount']",
     "root_cause": "export_csv writes its column names in lowercase.",
     "workaround": "Expect lowercase column names in the exported CSV.",
     "evidence": 'writer.writerow(["description", "amount"])',
     "last_used_session": 1, "expected": "expired"},
]

SESSIONS = {
    "s1": "2026-02-03", "s2": "2026-02-10", "s3": "2026-02-17", "s4": "2026-02-24", "s5": "2026-03-03",
}

# New failures at the new tag, one per memory. Each should match its memory.
NEW_FAILURES = {
    "m01": "FAILED tests/test_invoice.py::test_total - assert Decimal('0.30000000000000004') == Decimal('0.30')",
    "m02": "FAILED tests/test_misc.py::test_export - UnicodeEncodeError: 'ascii' codec can't encode character '\\xe9'",
    "m03": "FAILED tests/test_misc.py::test_discount_once - AssertionError: assert Decimal('81.000') == Decimal('90')",
    "m04": "FAILED tests/test_misc.py::test_business_vat - KeyError: 'vat_number'",
    "m05": "FAILED tests/test_misc.py::test_currency - ValueError: unknown currency 'EURO'",
    "m06": "FAILED tests/test_misc.py::test_numbering - AssertionError: assert 'INV-0002' == 'INV-0001'",
    "m07": "ImportError while loading conftest: ModuleNotFoundError: No module named 'invoicekit'",
    "m08": "FAILED tests/test_dates.py::test_due_date_skips_weekend - assert datetime.date(2026, 1, 4) == datetime.date(2026, 1, 5)",
    "m09": "Python 3.9 job: TypeError: unsupported operand type(s) for |: 'type' and 'NoneType' in invoice.py",
    "m10": "FAILED tests/test_dates.py::test_today_is_a_date - assert datetime.date(2026, 4, 2) <= datetime.date(2026, 4, 1)",
    "m11": "FAILED tests/test_tax.py::test_vat_rounding - assert Decimal('2.06') == Decimal('2.05')",
    "m12": "FAILED tests/test_misc.py::test_numbering - passes alone, fails when run after other tests in a random order",
    "m13": "TypeError: Line.__init__() missing 1 required positional argument: 'amount' in tests/test_invoice.py",
    "m14": "FAILED tests/test_misc.py::test_export_header - assert ['description', 'amount'] == ['Description', 'Amount']",
}


# ---------------------------------------------------------------- building it

def git(*args: str, date: str = "2026-01-15T09:00:00") -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
           "GIT_AUTHOR_NAME": "Dana Okafor", "GIT_AUTHOR_EMAIL": "dana@invoicekit.example",
           "GIT_COMMITTER_NAME": "Dana Okafor", "GIT_COMMITTER_EMAIL": "dana@invoicekit.example"}
    result = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
                            cwd=REPO, env=env, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def write(path: str, text: str) -> None:
    target = REPO / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def build_repo() -> tuple[str, str]:
    shutil.rmtree(REPO, ignore_errors=True)
    REPO.mkdir()
    git("init", "-q", "-b", "main")
    for path, text in OLD_FILES.items():
        write(path, text)
    git("add", "-A")
    git("commit", "-q", "-m", "Initial release", date="2026-01-15T09:00:00")
    git("tag", "old")
    old_sha = git("rev-parse", "old")
    for day, (message, changes) in enumerate(NEW_COMMITS, start=10):
        for path, change in changes.items():
            write(path, change((REPO / path).read_text(encoding="utf-8")))
        git("add", "-A")
        git("commit", "-q", "-m", message, date=f"2026-03-{day}T10:00:00")
    git("tag", "new")
    return old_sha, git("rev-parse", "new")


def session_text(session: str, memories: list[dict], old_sha: str) -> str:
    lines = [f"# Triage session {session}", "",
             f"Date: {SESSIONS[session]}", f"Repo: {REPO_NAME}", f"Commit: {old_sha}", ""]
    for memory in memories:
        lines += [
            f"## Finding {memory['id']}", "",
            f"We looked at a failing build: {memory['failure']}.",
            f"Root cause: {memory['root_cause']}",
            f"Workaround: {memory['workaround']}",
            f"Files we looked at: {', '.join(memory['files'])}.",
            f"The line this depends on, in {memory['files'][0]}: `{memory['evidence']}`",
            "",
        ]
    return "\n".join(lines)


def ci_log(memory: dict, run: int, old_sha: str) -> str:
    return "\n".join([
        f"Run {run}  repo={REPO_NAME}  commit={old_sha[:12]}  workflow=CI  job=test (3.12)",
        "##[group]Run pytest -p no:randomly --maxfail=5",
        "============================= test session starts ==============================",
        "collected 12 items",
        "",
        f"E   {memory['failure']}",
        "=========================== short test summary info ============================",
        f"FAILED - {memory['failure']}",
        "##[error]Process completed with exit code 1.",
        "",
    ])


def main() -> None:
    old_sha, new_sha = build_repo()

    for folder in ("ci_logs", "sessions", "eval"):
        shutil.rmtree(HERE / folder, ignore_errors=True)
        (HERE / folder).mkdir()

    run = 100
    for memory in MEMORIES:
        for _ in range(2 if memory["id"] <= "m08" else 1):
            run += 1
            (HERE / "ci_logs" / f"run-{run}.log").write_text(ci_log(memory, run, old_sha), encoding="utf-8")

    for session in SESSIONS:
        mine = [memory for memory in MEMORIES if memory["session"] == session]
        (HERE / "sessions" / f"{session}.md").write_text(session_text(session, mine, old_sha), encoding="utf-8")

    with open(HERE / "memories.jsonl", "w", encoding="utf-8") as f:
        for memory in MEMORIES:
            record = {key: value for key, value in memory.items() if key not in ("expected",)}
            record.update({"repo": REPO_NAME, "commit": old_sha, "evidence_file": memory["files"][0]})
            f.write(json.dumps(record) + "\n")

    questions = [{"id": f"q{number:02d}", "failure": NEW_FAILURES[memory["id"]],
                  "expected_memory": memory["id"], "expected_verdict": memory["expected"]}
                 for number, memory in enumerate(MEMORIES, start=1)]
    (HERE / "eval" / "questions.json").write_text(json.dumps({"tag": "new", "questions": questions}, indent=2) + "\n")

    print(f"Built {REPO_NAME}: old={old_sha[:12]} new={new_sha[:12]}")
    print(f"{run - 100} CI logs, {len(SESSIONS)} sessions, {len(MEMORIES)} memories, {len(questions)} questions")


if __name__ == "__main__":
    main()
