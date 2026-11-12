"""Settings shared by the extraction server and the evaluation."""

from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
# Every extraction the agent submits, one JSON line per invoice.
EXTRACTIONS = RESULTS / "extractions.jsonl"
# The invoices a person must check, with their failing fields.
REVIEW_QUEUE = RESULTS / "review_queue.jsonl"

# Invoices whose confidence is below this go to the review queue.
THRESHOLD = 0.6
