"""
Policy Agent - analyzes warranty, return, and refund policies.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from agent.state import AgentMessage, Claim, ClaimType, EvidenceChunk, PolicyDecision
from ingestion.labels import get_label, merge_labels

# Return and warranty windows are counted in calendar days as the customer experiences
# them, i.e. Beijing time.  These are A-share-market-adjacent consumer policies written for
# a China-based user, and `datetime.utcnow()` put the day boundary eight hours late: between
# 00:00 and 08:00 Beijing the UTC date is still yesterday, so a window that had just closed
# still read as open, and on the closing day the last valid day read as already past.
BEIJING = ZoneInfo("Asia/Shanghai")

# Phrases that refuse returns outright. A receipt that grants a return window while the
# merchant's own policy refuses returns is a conflict, and the workflow has to surface it
# rather than silently pick whichever document it read first — that is how a final-sale
# order ends up with a drafted return request.
_RETURN_REFUSAL_PATTERNS = (
    # plain refusals
    "final sale",
    "sales are final",
    "all sales final",
    "no returns",
    "no refunds",
    "no exchanges",
    "not accepted",
    "returns are not",
    "return is not",
    # eligibility refusals
    "non-returnable",
    "nonreturnable",
    "not returnable",
    "not eligible for return",
    "cannot be returned",
    "cannot be refunded",
    "ineligible for return",
    # refusals that only offer an exchange, or nothing at all
    "exchange only",
    "exchange-only",
    "exchange or store credit",
    "refunds are unavailable",
    "refund is unavailable",
    "returns are unavailable",
    "refund unavailable",
)


def policy_agent_now() -> datetime:
    """Current time in Beijing. The clock seam: tests replace this, production calls it."""
    return datetime.now(BEIJING)


def _local_date(moment: datetime) -> date:
    """The Beijing calendar date for a moment, naive values read as Beijing local time."""
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(BEIJING).date()


def parse_days(text: str) -> int | None:
    """Extract a number of days from policy text."""
    patterns = [
        r"(\d+)\s*[- ]?\s*(?:days|day)",
        r"(\d+)\s*[- ]?\s*(?:years|year)",
        r"(\d+)\s*[- ]?\s*(?:months|month)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            unit = m.group(0)
            if "year" in unit:
                return val * 365
            if "month" in unit:
                return val * 30
            return val
    return None


def run_policy_agent(state: dict) -> dict:
    """Analyze return and warranty policies from evidence chunks."""
    chunks: list[EvidenceChunk] = state.get("retrieved_evidence", [])
    # Receipts state policy lines too ("Return Policy: 30 days from purchase date"), and in the
    # sample cases the return window lives there while the warranty card phrases it in a form
    # the pattern below does not match.
    policy_chunks = [
        c
        for c in chunks
        if c.metadata.get("doc_type") in ("warranty", "policy", "receipt")
    ]

    all_text = " ".join(c.text for c in policy_chunks).lower()

    # Labels first. These were captured while the document's own structure was available (an
    # HTML block, a text line), so the label/value pairing is exact rather than reconstructed
    # from flattened prose. The text patterns below stay as a fallback for anything unlabelled.
    labels = merge_labels(policy_chunks)

    decision = PolicyDecision()

    # Extract return window
    labelled_window = get_label(
        labels, "return window", "return policy", "return period", "returns"
    )
    if labelled_window is not None:
        labelled_days = parse_days(labelled_window)
        if labelled_days is not None:
            decision.return_window_days = labelled_days
            decision.confidence = max(decision.confidence, 0.9)

    if decision.return_window_days is None:
        # Fallback: accepts both "30 days" and "30-day", since warranty cards hyphenate it.
        return_match = re.search(
            r"return\s*(?:within|policy|window|period)[:\s]*(\d+)\s*[- ]?\s*(?:day|days)",
            all_text,
        )
        if return_match is None:
            # A hyphenated lead-in, e.g. "0-day return window".
            return_match = re.search(
                r"(\d+)\s*[- ]\s*days?\s+return\s+window", all_text
            )
        if return_match:
            decision.return_window_days = int(return_match.group(1))
            # A parsed return window is evidence of a real policy read; without this the
            # decision kept the default 0.0 when no warranty period was present, publishing
            # claims at confidence 0.0.
            decision.confidence = max(decision.confidence, 0.85)

    # Extract warranty period
    warranty_match = re.search(
        r"warranty[:\s]*(\d+)\s*(?:year|years|month|months|day|days)", all_text
    )
    if warranty_match:
        decision.warranty_period = warranty_match.group(0)
        decision.confidence = max(decision.confidence, 0.85)
    else:
        # Look for 1-year as default in many consumer policies
        if "1 year" in all_text or "one year" in all_text or "12 month" in all_text:
            decision.warranty_period = "1 year"
            decision.confidence = max(decision.confidence, 0.7)
        else:
            # Fallback to the labelled value. The period phrase itself is kept ("2 years",
            # not "730 days") so the claim reads the way the document states it.
            labelled_warranty = get_label(
                labels, "warranty period", "warranty", "manufacturer warranty"
            )
            if labelled_warranty is not None:
                # Longest alternatives first: with (?:year|years) the pattern matches
                # "2 year" and drops the trailing "s".
                period = re.search(
                    r"(\d+)\s*[- ]?\s*(?:years|year|months|month|days|day)",
                    labelled_warranty,
                    re.IGNORECASE,
                )
                if period:
                    decision.warranty_period = period.group(0).lower()
                    decision.confidence = max(decision.confidence, 0.85)

    # Extract exceptions
    exception_keywords = [
        "does not cover", "excluded", "not covered", "exception",
        "void", "not include", "damage caused by", "abuse",
        "unauthorized", "modification", "accidental damage",
    ]
    for kw in exception_keywords:
        if kw in all_text:
            decision.exceptions.append(kw)

    # Check if return is still valid (if we have order info)
    order_messages = [m for m in state.get("agent_messages", []) if m.agent_name == "order_agent"]
    purchase_date_str = None
    for msg in order_messages:
        for claim in msg.claims:
            if "purchase date" in claim.text.lower():
                purchase_date_str = claim.text.split(":")[-1].strip()

    if purchase_date_str:
        try:
            purchase_date = datetime.strptime(purchase_date_str.split()[0], "%Y-%m-%d")
            # Beijing calendar days, not UTC: see policy_agent_now() above.
            days_since = (_local_date(policy_agent_now()) - purchase_date.date()).days

            if decision.return_window_days is not None:
                if decision.return_window_days == 0:
                    # "0 days" is final sale stated in numbers: the window never opened. It is
                    # a decision, not an absent value, so the verdict is False rather than
                    # "undetermined".
                    decision.is_return_valid = False
                else:
                    decision.is_return_valid = days_since <= decision.return_window_days

            # Warranty is typically longer than return window, and is decided independently:
            # a policy can state a warranty period without stating a return window, in which
            # case gating this on return_window_days would leave the warranty undecided.
            if decision.warranty_period:
                warranty_days = parse_days(decision.warranty_period)
                if warranty_days is not None:
                    decision.is_warranty_valid = days_since <= warranty_days
        except (ValueError, IndexError):
            pass

    claims = []
    if decision.return_window_days is not None:
        if decision.is_return_valid is None:
            status = "undetermined"  # a missing purchase date is not the same as "past"
        elif decision.is_return_valid:
            status = "within"
        else:
            status = "past"
        claims.append(
            Claim(
                claim_id="policy_return_window",
                text=(
                    f"Return window: {decision.return_window_days} days ({status} window)"
                    if decision.return_window_days
                    else "Return window: 0 days (final sale - no return window)"
                ),
                claim_type=ClaimType.POLICY_RULE,
                confidence=decision.confidence,
                uncertainty=(
                    None
                    if decision.is_return_valid is not None
                    else "Cannot determine purchase date"
                ),
            )
        )
    # Same contract as the warranty verdict below: the id carries the answer, and the claim is
    # absent when the dates did not allow one.
    if decision.is_return_valid is not None:
        claims.append(
            Claim(
                claim_id=(
                    "policy_return_valid"
                    if decision.is_return_valid
                    else "policy_return_expired"
                ),
                text=(
                    "The return window is still open"
                    if decision.is_return_valid
                    else "The return window has closed"
                ),
                claim_type=ClaimType.POLICY_RULE,
                confidence=decision.confidence,
            )
        )
    if decision.warranty_period:
        claims.append(
            Claim(
                claim_id="policy_warranty_period",
                text=f"Warranty period: {decision.warranty_period}",
                claim_type=ClaimType.POLICY_RULE,
                confidence=decision.confidence,
            )
        )
    # The verdict is carried in the claim_id so downstream agents read a field rather than
    # re-parsing prose. Absent entirely when the dates did not allow a decision, which lets
    # action_agent tell "expired" apart from "could not determine".
    if decision.is_warranty_valid is not None:
        claims.append(
            Claim(
                claim_id=(
                    "policy_warranty_valid"
                    if decision.is_warranty_valid
                    else "policy_warranty_expired"
                ),
                text=(
                    "Warranty coverage is still valid"
                    if decision.is_warranty_valid
                    else "Warranty coverage has expired"
                ),
                claim_type=ClaimType.POLICY_RULE,
                confidence=decision.confidence,
            )
        )
    if decision.exceptions:
        claims.append(
            Claim(
                claim_id="policy_exceptions",
                text=f"Policy exceptions found: {', '.join(decision.exceptions[:3])}",
                claim_type=ClaimType.POLICY_RULE,
                confidence=0.7,
            )
        )

    # A window in one document and a refusal in another is a conflict, not two facts to be
    # ranked. A refusal on its own (or a zero-day window) is simply "returns are not
    # available". Either way it is recorded as its own claim so downstream agents read a
    # field rather than re-scanning the prose.
    refusal_hits = [p for p in _RETURN_REFUSAL_PATTERNS if p in all_text]
    if refusal_hits and decision.return_window_days is not None:
        claims.append(
            Claim(
                claim_id="policy_return_conflict",
                text=(
                    "Conflicting return terms: the receipt states a "
                    f"{decision.return_window_days}-day return window, but the "
                    f"merchant's policy refuses returns ({', '.join(refusal_hits[:3])})"
                ),
                claim_type=ClaimType.RISK,
                confidence=0.9,
                uncertainty="The documents disagree about whether a return is possible",
            )
        )
    elif refusal_hits or decision.return_window_days == 0:
        reason = (
            ", ".join(refusal_hits[:3])
            if refusal_hits
            else "the stated return window is 0 days"
        )
        claims.append(
            Claim(
                claim_id="policy_return_unavailable",
                text=f"Returns are not available for this order ({reason})",
                claim_type=ClaimType.RISK,
                confidence=0.9,
                uncertainty="No self-service return path exists for this order",
            )
        )

    message = AgentMessage(
        agent_name="policy_agent",
        status="success" if claims else "needs_more_evidence",
        claims=claims,
        evidence_ids=[c.chunk_id for c in policy_chunks],
        confidence=decision.confidence or 0.5,
        next_actions=["product_agent"],
    )

    return {
        **state,
        "agent_messages": state.get("agent_messages", []) + [message],
    }
