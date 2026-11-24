# Extract Invoices with Confidence Scores and a Review Queue

A finance team receives ad-buy invoices from TV stations as PDFs. Some have a text layer, others are scans. An agent extracts each invoice's fields, but the model doesn't say when it's unsure, and a misread amount or date that slips through costs money.

Your job is to make the extraction server check every extraction the agent submits, give it a confidence score, and send the uncertain ones to a person for review. Then you'll measure how accurate the extraction is, and choose the threshold that catches the most errors without flooding the reviewer.

The invoices are ad-buy forms from the [VRDU benchmark](https://github.com/google-research-datasets/vrdu): 30 for the evaluation, 17 digital and 13 scanned.
## Exercise structure

- [`extraction_server.py`](extraction_server.py): the MCP server, with its two tools, `read_invoice` and `submit_extraction`, and the checks behind `submit_extraction`: `validate`, `cross_checks` and `field_confidence`.
- [`config.py`](config.py): where the results are saved, and the review `THRESHOLD`.
- [`evaluate.py`](evaluate.py): runs the agent on the 30 invoices, then measures per-field accuracy by document type, and how well the review queue catches the wrong extractions at several thresholds.
- [`opencode.jsonc`](opencode.jsonc): the agent configuration. It registers `extraction_server.py` as the `invoice` MCP server.
- [`.opencode/agents/extraction-agent.md`](.opencode/agents/extraction-agent.md): the agent's system prompt.
- [`invoices.py`](../invoices.py): the invoice schema, `AdBuyInvoice`, the functions that read a PDF's pages, and the comparison with the ground truth.
- [`data/`](../data/): [`invoices.json`](../data/invoices.json), which lists the invoices, and [`setup_data.py`](../data/setup_data.py), which downloads them.
- [`shared/agent_runs.py`](../../shared/agent_runs.py): the functions that run the agent.

## Tasks

1. **Understand the invoices.** Once you've downloaded the invoices, open a digital and a scanned one in `../data/pdfs/`, and find their fields in `../data/ground_truth.json`.
2. **Read the pages.** Complete `read_invoice` in [`extraction_server.py`](extraction_server.py), so the agent gets each page's text, or an image of the page when it's scanned.
3. **Validate the extraction.** Complete `validate`, which checks the agent's extraction against the Pydantic schema, `AdBuyInvoice`. It keeps the valid fields and records why each invalid one failed, so one bad field doesn't lose the whole invoice.
4. **Cross-check the fields.** Complete `cross_checks`: the line items' amounts add up to the invoice total, and neither the flight nor any line item ends before it starts.
5. **Score the confidence.** Complete `field_confidence`, which lowers a field's confidence when the invoice was scanned, or when the field failed validation, is missing, or failed a cross-check.
6. **Send uncertain invoices for review.** Complete `submit_extraction`. An invoice's confidence is its lowest field score. Below `THRESHOLD`, it goes to the review queue, with its failing fields and why, and the agent is told.
7. **Measure and choose a threshold.** Complete `escalation` in [`evaluate.py`](evaluate.py), then run it. How does accuracy differ between digital and scanned invoices? From the threshold table, how many wrong invoices does each threshold let through, and how many right ones does it send to a person? Set the `THRESHOLD` you choose in [`config.py`](config.py).

> **Important:** don't change the agent's prompt or [`invoices.py`](../invoices.py). The evaluation should measure only your checks.

## Set up and run

1. Download the invoices and their ground truth, once:

   ```bash
   python3 ../data/setup_data.py
   ```

2. Set your keys for the model:

   ```bash
   export OPENAI_API_KEY=<your key>
   export OPENAI_BASE_URL=<your base URL>
   ```

3. Run the agent on every invoice, then score the results. To score the saved results again, for example after changing `THRESHOLD`, without running the agent, add `--score`:

   ```bash
   python3 evaluate.py
   python3 evaluate.py --score
   ```

## Deliverables

- A completed [`extraction_server.py`](extraction_server.py).
- A completed [`evaluate.py`](evaluate.py).
- The output of `evaluate.py`: the accuracy by document type, and the threshold table.
