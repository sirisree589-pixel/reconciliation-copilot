"""
reconciler.py

Core matching/reconciliation engine for the Vendor Reconciliation Copilot.

Design decision (explain this in your demo video):
The matching logic itself is 100% deterministic Python - no LLM involved.
An LLM is only used *after* this engine has produced results, to turn
structured discrepancies into a plain-English summary. This keeps the
reconciliation result auditable and reproducible, which matters a lot
when the output affects real money.
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


# How close two amounts need to be to still count as "matched"
# (accounts for rounding, small fees, etc.)
AMOUNT_TOLERANCE = 0.01


@dataclass
class ReconciliationResult:
    matched: pd.DataFrame
    amount_mismatches: pd.DataFrame
    vendor_only: pd.DataFrame       # in vendor statement, missing from our ledger
    ledger_only: pd.DataFrame       # in our ledger, missing from vendor statement
    running_balance: float = 0.0
    total_vendor_amount: float = 0.0
    total_ledger_amount: float = 0.0


def normalize_vendor_statement(df: pd.DataFrame) -> pd.DataFrame:
    """Map the vendor statement's columns into our common internal schema."""
    out = pd.DataFrame({
        "source": "vendor",
        "source_id": df["transaction_id"],
        "date": pd.to_datetime(df["date"]),
        "reference": df["reference"].astype(str).str.strip().str.upper(),
        "description": df["description"],
        "amount": df["amount"].astype(float),
    })
    return out


def normalize_internal_ledger(df: pd.DataFrame) -> pd.DataFrame:
    """Map the internal ledger's columns into the same common schema."""
    out = pd.DataFrame({
        "source": "ledger",
        "source_id": df["entry_id"],
        "date": pd.to_datetime(df["posting_date"]),
        "reference": df["ref_number"].astype(str).str.strip().str.upper(),
        "description": df["narration"],
        "amount": df["value"].astype(float),
    })
    return out


def reconcile(vendor_df: pd.DataFrame, ledger_df: pd.DataFrame) -> ReconciliationResult:
    """
    Match vendor statement rows to internal ledger rows by reference number
    (the invoice/reference number is treated as the natural join key - this
    is the same approach a human accountant uses when reconciling by hand).

    For every reference present in both sources:
      - if amounts agree within tolerance -> matched
      - if amounts disagree -> amount_mismatch
    For every reference only in the vendor statement -> vendor_only
    For every reference only in the internal ledger -> ledger_only
    """
    v = normalize_vendor_statement(vendor_df)
    l = normalize_internal_ledger(ledger_df)

    merged = v.merge(
        l,
        on="reference",
        how="outer",
        suffixes=("_vendor", "_ledger"),
        indicator=True,
    )

    matched_rows = []
    mismatch_rows = []
    vendor_only_rows = []
    ledger_only_rows = []

    for _, row in merged.iterrows():
        if row["_merge"] == "both":
            v_amt = row["amount_vendor"]
            l_amt = row["amount_ledger"]
            diff = round(v_amt - l_amt, 2)
            record = {
                "reference": row["reference"],
                "description": row["description_vendor"],
                "vendor_amount": v_amt,
                "ledger_amount": l_amt,
                "difference": diff,
                "vendor_date": row["date_vendor"].date(),
                "ledger_date": row["date_ledger"].date(),
            }
            if abs(diff) <= AMOUNT_TOLERANCE:
                matched_rows.append(record)
            else:
                mismatch_rows.append(record)
        elif row["_merge"] == "left_only":
            vendor_only_rows.append({
                "reference": row["reference"],
                "description": row["description_vendor"],
                "amount": row["amount_vendor"],
                "date": row["date_vendor"].date(),
            })
        else:  # right_only
            ledger_only_rows.append({
                "reference": row["reference"],
                "description": row["description_ledger"],
                "amount": row["amount_ledger"],
                "date": row["date_ledger"].date(),
            })

    matched_df = pd.DataFrame(matched_rows)
    mismatch_df = pd.DataFrame(mismatch_rows)
    vendor_only_df = pd.DataFrame(vendor_only_rows)
    ledger_only_df = pd.DataFrame(ledger_only_rows)

    total_vendor = v["amount"].sum()
    total_ledger = l["amount"].sum()
    # Running/reconciling balance = what's left unexplained between the two books
    running_balance = round(total_vendor - total_ledger, 2)

    return ReconciliationResult(
        matched=matched_df,
        amount_mismatches=mismatch_df,
        vendor_only=vendor_only_df,
        ledger_only=ledger_only_df,
        running_balance=running_balance,
        total_vendor_amount=round(total_vendor, 2),
        total_ledger_amount=round(total_ledger, 2),
    )


def build_summary(result: ReconciliationResult, use_llm: bool = False, api_key: Optional[str] = None) -> str:
    """
    Produce a plain-English summary of the reconciliation outcome.

    Default behaviour is a deterministic, template-based summary (fast,
    free, always available - good for a live demo with no network risk).

    If use_llm=True and an api_key is supplied, we instead ask an LLM to
    phrase the same structured facts more naturally. The LLM never sees
    raw data beyond what the engine already computed - it only rephrases
    facts, it does not decide what the facts are. That decision boundary
    is the design tradeoff worth mentioning in your demo video.
    """
    facts = _summary_facts(result)

    if not use_llm:
        return _template_summary(facts)

    try:
        return _llm_summary(facts, api_key)
    except Exception as e:
        # Never let a demo fail because of an API hiccup - fall back gracefully
        return _template_summary(facts) + f"\n\n(Note: LLM summary unavailable, showing template summary. {e})"


def _summary_facts(result: ReconciliationResult) -> dict:
    return {
        "matched_count": len(result.matched),
        "mismatch_count": len(result.amount_mismatches),
        "vendor_only_count": len(result.vendor_only),
        "ledger_only_count": len(result.ledger_only),
        "running_balance": result.running_balance,
        "total_vendor_amount": result.total_vendor_amount,
        "total_ledger_amount": result.total_ledger_amount,
        "mismatches": result.amount_mismatches.to_dict("records"),
        "vendor_only": result.vendor_only.to_dict("records"),
        "ledger_only": result.ledger_only.to_dict("records"),
    }


def _template_summary(facts: dict) -> str:
    lines = []
    lines.append(
        f"Reconciliation complete: {facts['matched_count']} transactions matched cleanly "
        f"between the vendor statement and the internal ledger."
    )
    lines.append(
        f"Vendor statement total: {facts['total_vendor_amount']:,.2f} | "
        f"Internal ledger total: {facts['total_ledger_amount']:,.2f} | "
        f"Unexplained difference: {facts['running_balance']:,.2f}"
    )

    if facts["mismatch_count"]:
        lines.append(f"\n{facts['mismatch_count']} transaction(s) matched by reference but amounts disagree:")
        for m in facts["mismatches"]:
            lines.append(
                f"  - {m['reference']} ({m['description']}): vendor shows {m['vendor_amount']:,.2f}, "
                f"ledger shows {m['ledger_amount']:,.2f}, difference of {m['difference']:,.2f}."
            )

    if facts["vendor_only_count"]:
        lines.append(f"\n{facts['vendor_only_count']} transaction(s) appear on the vendor statement "
                      f"but are missing from our internal ledger:")
        for r in facts["vendor_only"]:
            lines.append(f"  - {r['reference']} ({r['description']}): {r['amount']:,.2f}")

    if facts["ledger_only_count"]:
        lines.append(f"\n{facts['ledger_only_count']} transaction(s) appear in our internal ledger "
                      f"but are missing from the vendor statement:")
        for r in facts["ledger_only"]:
            lines.append(f"  - {r['reference']} ({r['description']}): {r['amount']:,.2f}")

    if not facts["mismatch_count"] and not facts["vendor_only_count"] and not facts["ledger_only_count"]:
        lines.append("\nNo discrepancies found - both books are fully in agreement.")

    return "\n".join(lines)


def _llm_summary(facts: dict, api_key: str) -> str:
    import requests
    prompt = (
        "You are an accounting assistant. Given these reconciliation facts as JSON, "
        "write a short, clear, plain-English summary (max 150 words) for a finance "
        "reviewer. Only state facts given below, do not invent numbers.\n\n"
        f"{facts}"
    )
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]
