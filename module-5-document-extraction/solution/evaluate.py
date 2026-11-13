"""Run the extraction agent on the 30 evaluation invoices, then measure per-field
accuracy by document type, and how well escalation catches the wrong extractions.

    python3 evaluate.py           # run the agent on every invoice, then score
    python3 evaluate.py --score   # score the saved results again, e.g. to try thresholds
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parent))
from config import EXTRACTIONS, REVIEW_QUEUE, THRESHOLD
from invoices import (
    FIELDS,
    AdBuyInvoice,
    field_correct,
    line_items_correct,
    load_ground_truth,
    load_invoices,
)
from shared.agent_runs import run_agent

AGENT = "extraction-agent"
THRESHOLDS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def run_all() -> None:
    """Process every evaluation invoice with the agent, starting from empty results."""
    for path in (EXTRACTIONS, REVIEW_QUEUE):
        path.unlink(missing_ok=True)
    for invoice in load_invoices("eval"):
        print(f"Processing {invoice['file']} ({invoice['kind']})...")
        run_agent(AGENT, f"Process the invoice {invoice['file']}.", HERE)


def load_results() -> dict[str, dict]:
    """The last extraction submitted for each invoice."""
    results = {}
    for line in EXTRACTIONS.read_text().splitlines():
        record = json.loads(line)
        results[record["file"]] = record
    return results


def score_document(record: dict, truth: dict) -> tuple[dict[str, bool | None], bool]:
    """Whether each field is right, using VRDU's match functions, and whether the
    document as a whole is wrong.

    A field's score is True (right), False (wrong), or None when the ground truth
    has no value for it, so there's nothing to check.
    """
    invoice = AdBuyInvoice.model_validate(record["invoice"])
    scores = {field: field_correct(field, invoice, truth) for field in FIELDS}
    scores["line_items"] = line_items_correct(invoice, truth)
    # TODO: a document is wrong when at least one field disagrees with the ground truth.
    # Hint: a None score isn't wrong, so test for False, not for "not correct".
    wrong = any(correct is False for correct in scores.values())
    return scores, wrong


def accuracy_by_type(rows: list[dict]) -> None:
    """The share of fields extracted correctly, for digital and scanned invoices."""
    print(f"\n{'field':<14} {'digital':>10} {'scanned':>10}")
    for field in FIELDS + ["line_items"]:
        cells = []
        for kind in ("digital", "scanned"):
            values = [
                row["scores"][field]
                for row in rows
                if row["kind"] == kind and row["scores"][field] is not None
            ]
            cells.append(
                f"{sum(values) / len(values):.2f} ({len(values)})" if values else "-"
            )
        print(f"{field:<14} {cells[0]:>10} {cells[1]:>10}")


def escalation(rows: list[dict], threshold: float) -> dict:
    """Measure how well the confidence score picks out the invoices that need review.

    Escalating means sending an invoice to the review queue, for a person to check.
    The ideal threshold sends every wrong invoice (at least one field disagrees with
    the ground truth) and no right ones. This compares the two lists at one threshold:

      escalated       invoices with confidence below the threshold: a person checks them
      auto_processed  the rest: their data is used without anyone checking it
      missed_errors   wrong invoices that were auto-processed: the costly mistakes
      precision       of the escalated invoices, the share that were really wrong.
                      Low precision wastes the reviewer's time on correct invoices.

    Raising the threshold escalates more invoices: fewer errors are missed, but a
    person has more invoices to check. main() prints this for several thresholds,
    to choose one.
    """
    # TODO: Step 1. Find the escalated invoices: confidence below the threshold.
    escalated = [row for row in rows if row["confidence"] < threshold]
    # TODO: Step 2. Find the wrong invoices, and the wrong ones that were escalated.
    # Hint: each row's "wrong" was set by score_document, which compares
    # the extraction with the ground truth (data/ground_truth.json).
    wrong = [row for row in rows if row["wrong"]]
    caught = [row for row in escalated if row["wrong"]]
    # TODO: Step 3. Compute the counts and the precision described above.
    # Hint: return None when there's nothing to divide by, e.g. nothing escalated.
    return {
        "escalated": len(escalated),
        "auto_processed": len(rows) - len(escalated),
        "missed_errors": len(wrong) - len(caught),
        "precision": len(caught) / len(escalated) if escalated else None,
    }


def main() -> None:
    if "--score" not in sys.argv:
        run_all()
    truth = load_ground_truth()
    results = load_results()
    rows = []
    for invoice in load_invoices("eval"):
        record = results.get(invoice["file"])
        if record is None:
            print(f"No extraction was submitted for {invoice['file']}.")
            continue
        scores, wrong = score_document(record, truth[invoice["file"]])
        rows.append(
            {
                "file": invoice["file"],
                "kind": invoice["kind"],
                "scores": scores,
                "wrong": wrong,
                "confidence": record["document_confidence"],
            }
        )

    print(
        f"\n{len(rows)} invoices scored: {sum(row['wrong'] for row in rows)} with at least one wrong field."
    )
    accuracy_by_type(rows)

    print(f"\nEscalation at the current threshold ({THRESHOLD}):")
    print(json.dumps(escalation(rows, THRESHOLD), indent=2))

    print(
        f"\n{'threshold':>9} {'escalated':>9} {'auto':>5} {'missed':>6} {'precision':>9}"
    )
    for threshold in THRESHOLDS:
        e = escalation(rows, threshold)
        fmt = lambda v: "-" if v is None else f"{v:.2f}"
        print(
            f"{threshold:>9.1f} {e['escalated']:>9} {e['auto_processed']:>5} {e['missed_errors']:>6} {fmt(e['precision']):>9}"
        )


if __name__ == "__main__":
    main()
