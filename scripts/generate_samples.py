from pathlib import Path
from io import BytesIO
import json

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def make_pdf(
    path: Path,
    label: str,
    doc_id: str,
    qty: int,
    *,
    destination: str = "Jl Merdeka 10 Bandung",
    recipient: str = "PT Maju Jaya",
) -> None:
    buf = BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    y = 800
    lines = [
        "Outurn Regression Fixture",
        f"{label} No: {doc_id}",
        "Shipment ID: SHP-DEMO-001",
        "Sender: PT Gudang Sentosa",
        f"Recipient: {recipient}",
        f"Destination: {destination}",
        "SKU | Description | Quantity | Unit Price | Line Total",
        f"SKU-001 | Minyak Goreng 1L | {qty} | 18000 | {qty * 18000}",
        f"Grand Total: {qty * 18000}",
    ]
    for line in lines:
        pdf.drawString(55, y, line)
        y -= 22
    pdf.save()
    path.write_bytes(buf.getvalue())


def generate(
    name: str,
    packing_qty: int,
    *,
    destinations: tuple[str, str, str] | None = None,
    recipients: tuple[str, str, str] | None = None,
) -> None:
    folder = SAMPLES / name
    folder.mkdir(parents=True, exist_ok=True)
    destinations = destinations or ("Jl Merdeka 10 Bandung",) * 3
    recipients = recipients or ("PT Maju Jaya",) * 3
    make_pdf(folder / "invoice.pdf", "Invoice", "INV-DEMO-001", 100, destination=destinations[0], recipient=recipients[0])
    make_pdf(folder / "packing-list.pdf", "Packing List", "PL-DEMO-001", packing_qty, destination=destinations[1], recipient=recipients[1])
    make_pdf(folder / "surat-jalan.pdf", "Surat Jalan", "DO-DEMO-001", 100, destination=destinations[2], recipient=recipients[2])
    (folder / "expected.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "expected_status": "CLEAR" if packing_qty == 100 else "HOLD",
                "expected_mismatches": [] if packing_qty == 100 else ["QUANTITY_MISMATCH"],
            },
            indent=2,
        ) + "\n"
    )


if __name__ == "__main__":
    generate("clear", 100)
    generate("hold-quantity", 90)
    generate(
        "review-destination",
        100,
        destinations=("Jl Merdeka 10 Bandung", "Jl Merdeka 10 Bandung", "Jl Asia Afrika 1 Cimahi"),
    )
    generate(
        "entity-normalization",
        100,
        recipients=("PT. Maju Jaya", "PT Maju Jaya", "PT MAJU JAYA"),
    )
