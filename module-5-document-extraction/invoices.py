"""What the demo and the exercise share: the invoice schema, reading PDFs, and
comparing an extraction with the ground truth using VRDU's match functions."""

from __future__ import annotations

import base64
import io
import json
from datetime import date
from pathlib import Path

import pdfplumber
from pydantic import BaseModel, Field

import vrdu_match_utils as match_utils

MODULE = Path(__file__).resolve().parent
DATA = MODULE / "data"
PDFS = DATA / "pdfs"
MIN_PAGE_CHARS = 20
IMAGE_RESOLUTION = 150


class LineItem(BaseModel):
    channel: str | None = Field(None, description="The channel number the ads air on, e.g. 9")
    program_desc: str | None = Field(None, description="Only the program or time slot from the Description column, e.g. M-F 5p-6p")
    program_start_date: date | None = Field(None, description="The first day this line item airs")
    program_end_date: date | None = Field(None, description="The last day this line item airs")
    sub_amount: float | None = Field(None, description="The line item's total Amount, not the rate per spot")


class AdBuyInvoice(BaseModel):
    advertiser: str | None = Field(None, description="The campaign or group buying the ads")
    agency: str | None = Field(None, description="The ad agency placing the order, if any")
    contract_num: str | None = Field(None, description="The contract or order number")
    property: str | None = Field(None, description="The TV station's call sign, e.g. KMSP")
    product: str | None = Field(None, description="The product or campaign the ads are for")
    tv_address: str | None = Field(None, description="The TV station's address")
    flight_from: date | None = Field(None, description="The first day the ads run")
    flight_to: date | None = Field(None, description="The last day the ads run")
    gross_amount: float | None = Field(None, description="The invoice total, before agency commission")
    line_items: list[LineItem] = Field(default_factory=list)


FIELDS = [name for name in AdBuyInvoice.model_fields if name != "line_items"]

# From VRDU's meta.json: how each field is compared with the ground truth.
MATCHERS = {
    "advertiser": match_utils.GeneralStringMatch,
    "agency": match_utils.GeneralStringMatch,
    "contract_num": match_utils.NumericalStringMatch,
    "flight_from": match_utils.DateMatch,
    "flight_to": match_utils.DateMatch,
    "gross_amount": match_utils.PriceMatch,
    "product": match_utils.GeneralStringMatch,
    "tv_address": match_utils.AddressMatch,
    "property": match_utils.GeneralStringMatch,
    "channel": match_utils.GeneralStringMatch,
    "program_desc": match_utils.GeneralStringMatch,
    "program_start_date": match_utils.DateMatch,
    "program_end_date": match_utils.DateMatch,
    "sub_amount": match_utils.PriceMatch,
}


def load_invoices(role: str | None = None) -> list[dict]:
    invoices = json.loads((DATA / "invoices.json").read_text())["invoices"]
    return [invoice for invoice in invoices if role is None or invoice["role"] == role]


def load_ground_truth() -> dict:
    return json.loads((DATA / "ground_truth.json").read_text())


def scanned_pages(path: Path) -> list[bool]:
    """For each page, whether it's scanned: pdfplumber finds (almost) no text on it."""
    with pdfplumber.open(path) as pdf:
        return [len(page.chars) < MIN_PAGE_CHARS for page in pdf.pages]


def page_text(path: Path, number: int) -> str:
    with pdfplumber.open(path) as pdf:
        return pdf.pages[number].extract_text() or ""


def page_png(path: Path, number: int) -> bytes:
    """One page as a PNG image."""
    with pdfplumber.open(path) as pdf:
        image = pdf.pages[number].to_image(resolution=IMAGE_RESOLUTION).original
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def page_image(path: Path, number: int) -> str:
    """One page as a PNG data URL, ready to send to a multimodal model."""
    return "data:image/png;base64," + base64.b64encode(page_png(path, number)).decode()


def as_text(value) -> str:
    """A value as text the match functions understand, e.g. dates as MM/DD/YYYY."""
    if isinstance(value, date):
        return value.strftime("%m/%d/%Y")
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def matches(field: str, value, labels: list[str]) -> bool:
    """Whether an extracted value matches any annotated mention of the field."""
    if value is None:
        return False
    return MATCHERS[field].match((as_text(value), None), [(label, None) for label in labels])


def field_correct(field: str, invoice: AdBuyInvoice, truth: dict) -> bool | None:
    """Whether one field is right. None when the invoice doesn't have that field."""
    labels = truth["fields"].get(field)
    if not labels:
        return None
    return matches(field, getattr(invoice, field), labels)


def line_items_correct(invoice: AdBuyInvoice, truth: dict) -> bool | None:
    """Whether every annotated line item was found, with the right program and amount."""
    gold = truth["line_items"]
    if not gold:
        return None
    for item in gold:
        found = any(
            all(
                matches(field, getattr(extracted, field), [item[field]])
                for field in ("program_desc", "sub_amount")
                if field in item
            )
            for extracted in invoice.line_items
        )
        if not found:
            return False
    return True
