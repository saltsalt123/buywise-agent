"""
Seed sample data into the data/uploads directory.
"""
from __future__ import annotations

import json
from pathlib import Path

SAMPLE_DIR = Path("sample_data")


def create_headphone_warranty_case():
    """Create synthetic sample files for the headphone warranty demo case."""
    case_dir = SAMPLE_DIR / "headphone_warranty_case"
    case_dir.mkdir(parents=True, exist_ok=True)

    # 1. Receipt PDF (as text-based PDF using reportlab-like text)
    # For the MVP, we create a text file that represents the receipt content
    receipt_text = """SONIC ELECTRONICS - SALES RECEIPT
----------------------------------------
Store #: 4217 - Downtown
Date: 2025-11-10 14:32:45
Cashier: Maria Chen

Item: SoundMax Pro Wireless Headphones
Model: SM-PRO-X1
SKU: SMPRX1-2025-BLK
Quantity: 1
Unit Price: $89.99
Total: $89.99

Payment: Visa ****4242
Auth Code: 7A3F2B

Order #: ORD-2025-11-10-8921

Return Policy: 30 days from purchase date
Warranty: 1 year manufacturer warranty included

Thank you for your purchase!
"""
    (case_dir / "receipt.txt").write_text(receipt_text)

    # 2. Warranty card text
    warranty_text = """SOUNDMAX PRO - LIMITED WARRANTY CARD
========================================
Product: SoundMax Pro Wireless Headphones (SM-PRO-X1)

WARRANTY PERIOD: 1 YEAR from date of purchase
COVERAGE: Manufacturer defects in materials and workmanship

What is covered:
- Charging port defects
- Battery failure under normal use
- Audio driver malfunction
- Bluetooth connectivity issues (hardware-related)
- Physical defects in materials

What is NOT covered:
- Accidental damage (drops, water, physical impact)
- Normal wear and tear (ear pads, battery degradation)
- Unauthorized modifications or repairs
- Lost or stolen products
- Damage caused by improper charging (non-certified chargers)

TO CLAIM WARRANTY:
1. Contact SoundMax support at support@soundmax.com or 1-800-555-SOUND
2. Provide proof of purchase (receipt)
3. Describe the issue and include photos if applicable
4. We will provide a prepaid return shipping label
5. Replacement or repair within 5-7 business days after receipt

RETURN POLICY: 30-day return window from purchase date
Extended holiday return: Purchases after Nov 1 - return by Jan 31

SOUNDMAX SUPPORT: support@soundmax.com | 1-800-555-7686
"""
    (case_dir / "warranty_card.txt").write_text(warranty_text)

    # 3. Support email conversation
    email_text = """From: customer@email.com
To: support@soundmax.com
Subject: SoundMax Pro Wireless Headphones - Not Charging
Date: 2026-06-05 19:22:14

Hi SoundMax Support,

I purchased the SoundMax Pro Wireless Headphones (Model: SM-PRO-X1) in November 2025. About two weeks ago, they stopped charging completely. I've tried different USB cables and power adapters, but the charging light doesn't turn on at all.

The headphones are otherwise in good condition - no drops, no water damage. I've used them normally for daily commuting.

Can you help me with a warranty claim?

Thanks,
[Customer]
---
From: support@soundmax.com
To: customer@email.com
Subject: Re: SoundMax Pro Wireless Headphones - Not Charging
Date: 2026-06-06 10:05:33

Dear Customer,

Thank you for contacting SoundMax support.

We're sorry to hear about the charging issue with your SoundMax Pro Wireless Headphones.

Based on your description, this sounds like it could be a charging port or battery issue, which is covered under our 1-year manufacturer warranty.

To proceed with a warranty claim, please:
1. Reply with a photo of your purchase receipt
2. Take a short video showing the charging issue (LED not lighting up)
3. Include your full name and shipping address

Once we receive these, we'll send you a prepaid return shipping label.

Best regards,
SoundMax Support Team
"""
    (case_dir / "support_email.eml").write_text(email_text)

    print("✅ Created headphone_warranty_case sample data")


def create_air_fryer_purchase_case():
    """Create synthetic sample data for purchase decision demo."""
    case_dir = SAMPLE_DIR / "air_fryer_purchase_case"
    case_dir.mkdir(parents=True, exist_ok=True)

    # Product page
    product_html = """<html><body>
<div class="product-page">
<h1>CrispMaster 5000 Air Fryer - $129.99</h1>
<div class="specs">
<p><strong>Capacity:</strong> 5.8 quarts</p>
<p><strong>Power:</strong> 1700W</p>
<p><strong>Temperature Range:</strong> 170°F - 400°F</p>
<p><strong>Dishwasher Safe:</strong> Yes (basket only)</p>
<p><strong>Warranty:</strong> 2 years limited</p>
<p><strong>Features:</strong> Digital touchscreen, 12 presets, shake reminder, keep warm function</p>
</div>
<div class="policy">
<p><strong>Return Policy:</strong> 30 days from delivery</p>
<p><strong>Price Match:</strong> Yes, within 14 days</p>
</div>
</div></body></html>"""
    (case_dir / "product_page.html").write_text(product_html)

    # Reviews CSV
    reviews_csv = """rating,title,review_text,verified_purchase
5,Love it!,Best air fryer I've owned. Food comes out perfectly crispy.,Yes
4,Great value,Works well for the price. Easy to clean.,Yes
3,Good but loud,It cooks well but the fan noise is quite loud.,Yes
5,Perfect for family,The 5.8qt is perfect for our family of four.,Yes
2,Stopped working after 3 months,Display stopped working randomly. Had to return.,Yes
4,Excellent air fryer,Food tastes great. Much healthier than deep frying.,Yes
1,Would not recommend,The basket coating started peeling after 2 months.,No
4,Very good,Simple to use and clean. Cooking times are accurate.,Yes
3,Decent,Good for basic air frying. The presets are hit or miss.,Yes
5,Amazing!,I use this every single day. Worth every penny.,Yes"""
    (case_dir / "reviews.csv").write_text(reviews_csv)

    print("✅ Created air_fryer_purchase_case sample data")


def create_laptop_return_case():
    case_dir = SAMPLE_DIR / "laptop_return_case"
    case_dir.mkdir(parents=True, exist_ok=True)

    receipt_text = """TECHWORLD INC. - SALES RECEIPT
----------------------------------------
Date: 2026-05-15 16:20:00
Order #: ORD-20260515-3342

Item: PowerBook Pro 15"
Model: PB-15-M3
Serial: SN-M31542-2026
Quantity: 1
Unit Price: $1,299.00
Total: $1,299.00

Payment: Visa ****1234

Return Policy: 14 days for laptops (unopened)
                30 days for accessories
"""
    (case_dir / "receipt.txt").write_text(receipt_text)

    policy_html = """<html><body>
<div class="return-policy">
<h1>TechWorld Return Policy</h1>
<p><strong>Return Window:</strong> 14 days from delivery for laptops and electronics</p>
<p><strong>Condition:</strong> Item must be in original packaging, unused condition</p>
<p><strong>Refund:</strong> Full refund to original payment method, 5-10 business days</p>
<p><strong>Restocking Fee:</strong> 15% restocking fee for opened laptops</p>
<p><strong>Exclusions:</strong> Software, consumables, custom orders</p>
</div></body></html>"""
    (case_dir / "return_policy.html").write_text(policy_html)

    bank_csv = """date,description,amount,balance
2026-05-15,TECHWORLD INC PURCHASE,-1299.00,3421.55
2026-05-16,TECHWORLD INC REFUND,1299.00,4720.55"""
    (case_dir / "bank_statement.csv").write_text(bank_csv)

    print("✅ Created laptop_return_case sample data")


def main():
    create_headphone_warranty_case()
    create_air_fryer_purchase_case()
    create_laptop_return_case()
    print("\n✅ All sample data created!")


if __name__ == "__main__":
    main()
