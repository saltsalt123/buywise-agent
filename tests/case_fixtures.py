"""Document-set builders shared by the pre-release verification tests.

Fixtures are written into a temporary directory at run time rather than committed under
``sample_data/``.  Two reasons:

* the contradictory case has to grant a return window that is still *open*, otherwise the
  run would take the "window has closed" path and the conflict would never be the thing
  under test — a committed fixture would carry a frozen purchase date and silently start
  testing something else as time passes;
* a fixture that is built per test cannot be left behind by a failed run.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

# The phrases a merchant uses to refuse returns. The policy agent treats these as
# conflicting with a stated return window.
FINAL_SALE_POLICY_HTML = """<html><body>
<div class="return-policy">
<h1>TechWorld Clearance Terms</h1>
<p><strong>Return Window:</strong> Final sale - no returns accepted on clearance items</p>
<p><strong>Condition:</strong> All sales final. Items are sold as-is.</p>
<p><strong>Refund:</strong> No refunds or exchanges are available for this order.</p>
</div></body></html>
"""

FINAL_SALE_EMAIL = """From: support@techworld.example
To: customer@email.example
Subject: Re: Return request for order ORD-20260515-3342
Date: Mon, 01 Jun 2026 10:05:33 +0800

Hello,

Thank you for your message. This order was placed during our clearance event and the
item is final sale, so we are not able to accept a return for it. No refunds or exchanges
apply to clearance purchases.

If you believe this is an error, please reply and a supervisor will review the order.

Best regards,
TechWorld Support
"""


def write_case(target: Path, files: dict[str, str]) -> str:
    """Materialise a document set and return its path as a string."""
    target.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (target / name).write_text(body)
    return str(target)


def receipt_with_return_window(purchase_date: str, days: int = 30) -> str:
    return (
        "TECHWORLD INC. - SALES RECEIPT\n"
        "----------------------------------------\n"
        f"Date: {purchase_date} 16:20:00\n"
        "Order #: ORD-20260515-3342\n\n"
        'Item: PowerBook Pro 15"\n'
        "Model: PB-15-M3\n"
        "Quantity: 1\n"
        "Unit Price: $1,299.00\n"
        "Total: $1,299.00\n\n"
        f"Return Policy: {days} days from purchase date\n"
        "Warranty: 1 year manufacturer warranty included\n"
    )


def contradictory_case(target: Path, days_ago: int = 5, window_days: int = 30) -> str:
    """A receipt granting a return window while the policy and support email refuse returns.

    The purchase date is placed ``days_ago`` before today so the window is *open*: the
    conflict, not expiry, has to be what the workflow reacts to.
    """
    purchase = (date.today() - timedelta(days=days_ago)).isoformat()
    return write_case(
        target,
        {
            "receipt.txt": receipt_with_return_window(purchase, window_days),
            "return_policy.html": FINAL_SALE_POLICY_HTML,
            "support_email.eml": FINAL_SALE_EMAIL,
        },
    )


def consistent_case(target: Path, days_ago: int = 5, window_days: int = 30) -> str:
    """Control: the same receipt with a policy that agrees with it."""
    purchase = (date.today() - timedelta(days=days_ago)).isoformat()
    return write_case(
        target,
        {
            "receipt.txt": receipt_with_return_window(purchase, window_days),
            "return_policy.html": (
                "<html><body><div class=\"return-policy\">"
                "<h1>TechWorld Return Policy</h1>"
                f"<p><strong>Return Window:</strong> {window_days} days from delivery</p>"
                "<p><strong>Refund:</strong> Full refund to original payment method</p>"
                "</div></body></html>"
            ),
        },
    )


def unparsable_case(target: Path) -> str:
    target.mkdir(parents=True, exist_ok=True)
    (target / "scan.bin").write_bytes(b"\x00\x01\x02 not a supported document")
    (target / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return str(target)
