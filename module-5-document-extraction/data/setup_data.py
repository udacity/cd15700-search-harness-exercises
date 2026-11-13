"""Download this module's invoices and their annotations.

They come from the VRDU benchmark's ad-buy forms.
https://github.com/google-research-datasets/vrdu (Creative Commons, see the paper:
https://arxiv.org/abs/2211.15421)

invoices.json lists the invoices we use. This script downloads their PDFs into pdfs/
and writes their annotations to ground_truth.json.

    python3 setup_data.py
"""

from __future__ import annotations

import gzip
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = "https://raw.githubusercontent.com/google-research-datasets/vrdu/main/ad-buy-form/main"


def download(url: str, path: Path) -> None:
    if not path.exists():
        print(f"Downloading {path.name}")
        urllib.request.urlretrieve(url, path)


def clean(text: str) -> str:
    return " ".join(text.split())


def ground_truth(annotations: list) -> dict:
    """The annotated value of every field, and of every line item.

    A field can appear several times on an invoice, so we keep every mention.
    A line item is annotated as a list of field names, with one mention each."""
    fields: dict[str, list[str]] = {}
    line_items = []
    for name, mentions in annotations:
        if isinstance(name, list):
            line_items.append(
                {field: clean(mention[0]) for field, mention in zip(name, mentions[0])}
            )
        else:
            fields[name] = [clean(mention[0]) for mention in mentions]
    return {"fields": fields, "line_items": line_items}


def main() -> None:
    invoices = json.loads((HERE / "invoices.json").read_text())["invoices"]
    (HERE / "pdfs").mkdir(exist_ok=True)
    download(f"{SOURCE}/dataset.jsonl.gz", HERE / "dataset.jsonl.gz")
    for invoice in invoices:
        download(f"{SOURCE}/pdfs/{invoice['file']}", HERE / "pdfs" / invoice["file"])

    wanted = {invoice["file"] for invoice in invoices}
    truth = {}
    with gzip.open(HERE / "dataset.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["filename"] in wanted:
                truth[row["filename"]] = ground_truth(row["annotations"])
    (HERE / "ground_truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    print(f"{len(invoices)} invoices ready, with their ground truth.")


if __name__ == "__main__":
    main()
