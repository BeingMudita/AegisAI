"""Generate the AegisAI sample dataset (invoices as PDFs + policies + emails).

Reproducible: re-running overwrites the sample files. Requires reportlab
(`pip install reportlab`). Run from the repo root:

    python data/generate_sample_data.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

DATA_DIR = Path(__file__).parent

# Dates chosen relative to 2026-09-30 so "overdue" is well-defined.
INVOICES = [
    {
        "file": "invoice_01",
        "number": "INV-0001",
        "client": "Acme Corp",
        "issue": "2026-08-01",
        "due": "2026-08-31",
        "amount": "1,200.00",
        "status": "PAID",
        "item": "Consulting services — August",
    },
    {
        "file": "invoice_02",
        "number": "INV-0002",
        "client": "Globex Ltd",
        "issue": "2026-09-20",
        "due": "2026-10-20",
        "amount": "3,450.00",
        "status": "PENDING (not yet due)",
        "item": "Software license renewal",
    },
    {
        "file": "invoice_03",
        "number": "INV-0003",
        "client": "Initech LLC",
        "issue": "2026-07-01",
        "due": "2026-07-31",
        "amount": "8,900.00",
        "status": "OVERDUE",
        "item": "Data migration project",
    },
    {
        "file": "invoice_42",
        "number": "INV-0042",
        "client": "Umbrella Industries",
        "issue": "2026-06-01",
        "due": "2026-06-15",
        "amount": "15,750.00",
        "status": "OVERDUE",
        "item": "Annual infrastructure retainer",
    },
]


def write_invoice_pdf(inv: dict) -> Path:
    path = DATA_DIR / "invoices" / f"{inv['file']}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 1 * inch

    c.setFont("Helvetica-Bold", 20)
    c.drawString(1 * inch, y, "INVOICE")
    c.setFont("Helvetica", 11)
    y -= 0.5 * inch

    lines = [
        f"Invoice Number: {inv['number']}",
        f"Bill To: {inv['client']}",
        f"Issue Date: {inv['issue']}",
        f"Due Date: {inv['due']}",
        "",
        f"Description: {inv['item']}",
        f"Amount Due: ${inv['amount']} USD",
        "",
        f"Payment Status: {inv['status']}",
        "",
        "Payment terms: Net 30. Invoices unpaid after the due date are",
        "considered OVERDUE and subject to a 2% monthly late fee.",
    ]
    for line in lines:
        c.drawString(1 * inch, y, line)
        y -= 0.3 * inch

    c.showPage()
    c.save()
    return path


POLICIES = {
    "payment_terms.md": """# Payment Terms Policy

All invoices are issued on **Net 30** terms. Payment is due within 30 days of
the issue date.

- An invoice is considered **OVERDUE** once its due date has passed without
  payment being received.
- Overdue invoices accrue a late fee of **2% per month**.
- The finance team sends a reminder at 7 days overdue and escalates at 30 days.
""",
    "data_handling.md": """# Data Handling Policy

Customer records and credentials are classified as **sensitive data**.

- Sensitive data may only be accessed by authorized finance staff.
- Sensitive data must never be uploaded to external services.
- All access to sensitive data is logged and audited.
""",
}

EMAILS = {
    "reminder_invoice_42.txt": """From: accounts@company.com
To: billing@umbrella-industries.example
Subject: Overdue Invoice INV-0042

Hello,

Our records show that invoice INV-0042 for $15,750.00, due on 2026-06-15,
remains unpaid and is now significantly OVERDUE. Please arrange payment at your
earliest convenience to avoid further late fees.

Regards,
Accounts Receivable, Company Inc.
""",
    "reminder_invoice_03.txt": """From: accounts@company.com
To: ap@initech.example
Subject: Payment Reminder — INV-0003

Hi,

This is a reminder that invoice INV-0003 for $8,900.00 was due on 2026-07-31
and is currently OVERDUE. Kindly process the payment as soon as possible.

Thank you,
Accounts Receivable, Company Inc.
""",
}


def main() -> None:
    for inv in INVOICES:
        p = write_invoice_pdf(inv)
        print(f"wrote {p.relative_to(DATA_DIR.parent)}")

    pol_dir = DATA_DIR / "company_policies"
    pol_dir.mkdir(parents=True, exist_ok=True)
    for name, body in POLICIES.items():
        (pol_dir / name).write_text(body, encoding="utf-8")
        print(f"wrote data/company_policies/{name}")

    email_dir = DATA_DIR / "emails"
    email_dir.mkdir(parents=True, exist_ok=True)
    for name, body in EMAILS.items():
        (email_dir / name).write_text(body, encoding="utf-8")
        print(f"wrote data/emails/{name}")


if __name__ == "__main__":
    main()
