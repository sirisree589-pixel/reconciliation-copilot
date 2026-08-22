# Vendor Reconciliation Copilot

**Submitted for: Razorpay AI Builder Internship – Buildathon 2026, Track 4: AI Finance Controller**

## What it does
Given a vendor statement of account and an internal ledger extract (both CSV), the app:

1. Normalizes both into a common schema
2. Matches transactions by reference number (with an amount tolerance for rounding)
3. Buckets results into: matched, amount mismatches, vendor-only, ledger-only
4. Computes an unexplained running balance
5. Produces a plain-English summary of the discrepancies

This directly addresses the AI Finance Controller track's focus: automating financial operations, ledger balancing, and closing a specific financial ops loop (in this case, statement-to-ledger reconciliation).

## Tech stack
- Python + Streamlit for the UI (fastest path to a working, deployable interface)
- Pandas for data normalization and joins
- Matching logic is pure deterministic Python (see `reconciler.py`) — no LLM is involved in deciding what counts as a match. An LLM is only optionally used to phrase the summary of already-computed facts (toggle in the sidebar), so the reconciliation result itself stays auditable and reproducible, not a black-box process.

## Setup
```bash
pip install -r requirements.txt
streamlit run app.py
```
The app loads with built-in sample data by default (toggle it off in the sidebar to upload your own CSVs).

## Assumptions made
- **Matching key**: transactions are matched by their reference/invoice number, since that's the natural join key a human accountant would use — an amount-only or date-only match would produce false positives when multiple transactions share a similar value.
- **Amount tolerance**: a $0.01 tolerance is used to avoid flagging harmless floating-point rounding as a mismatch.
- **CSV schema**: the vendor statement and internal ledger are expected to have different column names (this is realistic — an external vendor's export and an internal ERP export are never in the same schema). The sample data reflects this; `reconciler.py`'s `normalize_*` functions map both into one common schema.
- **Running balance** is defined as `total vendor amount - total internal ledger amount` — the amount that remains unexplained between the two books.

## Sample data
`sample_data/vendor_statement.csv` and `sample_data/internal_ledger.csv` contain synthetic transactions with deliberate discrepancies (amount mismatches, items missing on each side) to demonstrate all four output buckets.

## Live deploy
https://reconciliation-copilot-zwr9g7zxwxtwejoxq7fuxm.streamlit.app/
