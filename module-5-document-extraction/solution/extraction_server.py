"""MCP server for an invoice extraction agent: it gives the agent each invoice's pages,
then scores the agent's extraction and sends the uncertain ones to a review queue."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pydantic import ValidationError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from invoices import FIELDS, PDFS, AdBuyInvoice, page_png, page_text, scanned_pages
from config import EXTRACTIONS, RESULTS, REVIEW_QUEUE, THRESHOLD

REQUIRED = {"advertiser", "contract_num", "flight_from", "flight_to", "gross_amount"}
SCANNED_CONFIDENCE = 0.75
MISSING_CONFIDENCE = 0.3
CHECK_PENALTY = 0.5
AMOUNT_TOLERANCE = 0.01

mcp = FastMCP("invoice")


@mcp.tool
def read_invoice(filename: str):
    """Read an invoice, page by page. A page with a text layer comes back as its
    text, and a scanned page comes back as an image of the page.

    Args:
        filename: The invoice's file name, e.g. "22dd7e4a-3f0b-25e9-10bd-5ce1e652126c.pdf".
    """
    path = PDFS / Path(filename).name
    parts = []
    # TODO: send each page's text, or an image of the page if it's scanned
    # For text and image pages add the page number
    # Hint: invoices.py has scanned_pages, page_text and page_png to help you.
    # Hint: return a page's text as a plain string.
    # Hint: use FastMCP's Image helper to return images from tools.
    # https://gofastmcp.com/docs/python-sdk/fastmcp-utilities-types#image
    for number, scanned in enumerate(scanned_pages(path)):
        if scanned:
            parts.append(f"Page {number + 1} (scanned):")
            parts.append(Image(data=page_png(path, number), format="png"))
        else:
            parts.append(f"Page {number + 1}:\n{page_text(path, number)}")
    # With no image, send one block of text: a list of strings would reach the model as JSON.
    if all(isinstance(part, str) for part in parts):
        return "\n\n".join(parts)
    return parts


def validate(raw: dict) -> tuple[AdBuyInvoice, dict[str, str]]:
    """Check the agent's extraction against the AdBuyInvoice schema.

    Pydantic is all or nothing: if one field is invalid, you get no invoice at all.
    But the later steps (cross-checks, confidence, saving) need an invoice, so here
    a bad field doesn't sink the rest. Each invalid field is emptied, and the reason
    is recorded instead, so that field can still be scored low and sent for review.

    "Invalid" means the wrong type or format, e.g. "a lot" for an amount. A valid
    but wrong value, e.g. the wrong total, passes here: the cross-checks catch those.

    Returns the invoice with its valid fields, and {field: reason} for the invalid ones.
    """
    errors: dict[str, str] = {}
    data = dict(raw)
    # Usually two rounds: the first finds every bad field, the second passes because
    # those fields are now empty. The limit only makes sure the loop can't run forever.
    for _ in range(len(FIELDS) + 1):
        try:
            return AdBuyInvoice.model_validate(data), errors
        except ValidationError as error:
            for problem in error.errors():
                # problem["loc"] is where the error is, e.g. ("flight_from",) or
                # ("line_items", 0, "sub_amount"): we keep the top-level field.
                field = str(problem["loc"][0])
                # Keep the rejected value in the reason, so a reviewer can see it.
                errors.setdefault(field, f"{problem['msg']} (got {problem['input']!r})")
                # Empty the field: the schema allows None (or no line items).
                data[field] = [] if field == "line_items" else None
    return AdBuyInvoice(), errors


def cross_checks(invoice: AdBuyInvoice) -> dict[str, str]:
    """Check that the fields agree with each other. Returns the fields that don't, with why."""
    failures: dict[str, str] = {}

    # TODO: Add a check to verify if the extracted amounts from the line items
    # add up to gross_amount, within AMOUNT_TOLERANCE.
    # If they don't, flag both gross_amount and line_items, with the reason:
    # we can't tell which one was misread.
    amounts = [
        item.sub_amount for item in invoice.line_items if item.sub_amount is not None
    ]
    if invoice.gross_amount and amounts:
        total = sum(amounts)
        if abs(total - invoice.gross_amount) > AMOUNT_TOLERANCE * invoice.gross_amount:
            reason = f"line items add up to {total:.2f}, not {invoice.gross_amount:.2f}"
            failures["gross_amount"] = failures["line_items"] = reason

    # TODO: Add a check to verify that the flight ends on or after its start date
    if (
        invoice.flight_from
        and invoice.flight_to
        and invoice.flight_from > invoice.flight_to
    ):
        failures["flight_from"] = failures["flight_to"] = (
            "the flight ends before it starts"
        )

    # TODO: Add a check to verify that each line item starts on or before it ends
    # Hint: if a line item has an earlier failure reason from the first check,
    # append to the previous reason instead of replacing it.
    for item in invoice.line_items:
        if (
            item.program_start_date
            and item.program_end_date
            and item.program_start_date > item.program_end_date
        ):
            reason = f"{item.program_desc} ends before it starts"
            if "line_items" in failures:
                reason = f"{failures['line_items']}; {reason}"
            failures["line_items"] = reason
    return failures


def field_confidence(
    invoice: AdBuyInvoice, scanned: bool, errors: dict, checks: dict
) -> dict[str, tuple[float, str]]:
    """Give each field a confidence between 0 and 1, with the reason when it's lowered.

    This is rule-based confidence scoring: a few fixed rules, applied in order,
    each based on what we already know about the field.

    The steps, for each field:
      1. Start at 1.0, or at SCANNED_CONFIDENCE if any page was scanned.
      2. Failed validation: 0, since validate() emptied the field.
      3. Otherwise, if a required field is missing (None), its score is replaced
         by MISSING_CONFIDENCE (0.3), whatever it was after step 1: a scanned
         field at 0.75 and a digital one at 1.0 both drop to 0.3. Not 0, because
         the invoice may really not have that field.
      4. Failed a cross-check: multiply score by CHECK_PENALTY.

    Returns {field: (confidence, reason)}, with an empty reason at 1.0.
    """
    confidence = {}
    for field in FIELDS + ["line_items"]:
        # TODO: Step 1. Start every field at 1.0, or at SCANNED_CONFIDENCE if the
        # invoice is scanned: the model read it from an image, which is less reliable.
        score, reason = (
            (SCANNED_CONFIDENCE, "read from a scanned page") if scanned else (1.0, "")
        )
        value = getattr(invoice, field)
        # TODO: Step 2. A field in errors (it failed validation) gets 0.
        if field in errors:
            score, reason = 0.0, f"failed validation: {errors[field]}"
        # TODO: Step 3. Otherwise, a REQUIRED field that is None gets MISSING_CONFIDENCE.
        elif field in REQUIRED and value is None:
            score, reason = MISSING_CONFIDENCE, "required field is missing"
        # TODO: Step 4. A field in checks (it failed a cross-check) has its score
        # multiplied by CHECK_PENALTY, and the check's reason becomes its reason.
        if field in checks:
            score, reason = score * CHECK_PENALTY, checks[field]
        confidence[field] = (round(score, 2), reason)
    return confidence


@mcp.tool
def submit_extraction(filename: str, invoice: dict) -> dict:
    """Submit an invoice's extracted details. Returns whether it was accepted or sent for review.

    Args:
        filename: The invoice's file name.
        invoice: The extracted fields:
            advertiser, agency, product.
            property: the TV station as the invoice names it, e.g. WABC-TV.
            contract_num: only the contract number, without the revision number,
                e.g. "2186808", not "2186808 / 26660858".
            tv_address: the station's full address: street, city, state and ZIP code,
                without its name or phone number.
            flight_from, flight_to: the first and last day the ads run, as YYYY-MM-DD.
                A two-digit year like 20 means 2020.
            gross_amount: the invoice total, as a number.
            line_items: one per line on the invoice, each with
                channel, the channel number;
                program_desc, only the program or time slot from the Description column,
                    e.g. M-F 5p-6p;
                program_start_date and program_end_date, as YYYY-MM-DD;
                sub_amount, the line's total amount, not the rate per spot.
    """
    path = PDFS / Path(filename).name
    scanned = any(scanned_pages(path))

    # TODO: apply the checks above to the agent's extraction: validate it against
    # the schema, run the cross-checks on the valid invoice, then score each field
    # with field_confidence.
    parsed, errors = validate(invoice)
    confidence = field_confidence(parsed, scanned, errors, cross_checks(parsed))
    # TODO: Compute the invoice confidence as the lowest field score.
    document_confidence = min(score for score, _ in confidence.values())

    RESULTS.mkdir(exist_ok=True)
    record = {
        "file": path.name,
        "scanned": scanned,
        "invoice": parsed.model_dump(mode="json"),
        "confidence": {field: score for field, (score, _) in confidence.items()},
        "document_confidence": document_confidence,
    }
    with open(EXTRACTIONS, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # TODO: if the invoice's confidence is below THRESHOLD, add it to the review queue.
    # The review queue is the list of invoices a person must check by hand before
    # their data is used (here, one JSON line per invoice in REVIEW_QUEUE).
    # To save the reviewer time, list only the fields below THRESHOLD, each with
    # its confidence and reason, so they know where to look and why.
    # Then tell the agent the invoice was sent for review, and why.

    failing = [
        {"field": field, "confidence": score, "reason": reason}
        for field, (score, reason) in confidence.items()
        if score < THRESHOLD
    ]

    if document_confidence < THRESHOLD:
        with open(REVIEW_QUEUE, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "file": path.name,
                        "document_confidence": document_confidence,
                        "failing": failing,
                    }
                )
                + "\n"
            )
        return {
            "status": "sent for review",
            "document_confidence": document_confidence,
            "failing": failing,
        }
    return {"status": "accepted", "document_confidence": document_confidence}


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
