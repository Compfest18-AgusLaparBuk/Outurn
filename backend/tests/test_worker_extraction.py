import io

from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.repositories.operations import OperationsRepository, OrganizationRow
from app.repositories.reconciliations import ReconciliationRepository
from app.services.document_storage import DocumentStorage
from app.worker import AssuranceWorker


def _pdf() -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output)
    for index, line in enumerate(
        [
            "Invoice No: INV-WORKER-001",
            "Shipment ID: SHP-WORKER-001",
            "Sender: PT Gudang Sentosa",
            "Recipient: PT Maju Jaya",
            "Destination: Jl Merdeka 10 Bandung",
            "SKU | Description | Quantity | Unit Price | Line Total",
            "SKU-001 | Minyak Goreng 1L | 100 | 18000 | 1800000",
            "Grand Total: 1800000",
        ]
    ):
        document.drawString(50, 800 - index * 22, line)
    document.save()
    return output.getvalue()


def test_worker_extracts_validated_vault_document(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'worker.db'}"
    reconciliation = ReconciliationRepository(database_url)
    operations = OperationsRepository(database_url)
    user = operations.ensure_system_user("worker@example.test")
    with operations.session_factory() as session:
        organization_id = session.scalar(
            select(OrganizationRow.id)
            .where(OrganizationRow.active.is_(True))
            .order_by(OrganizationRow.created_at.asc())
            .limit(1)
        )
    shipment = reconciliation.create_shipment(
        organization_id=organization_id,
        payload={
            "internal_reference": "SHP-WORKER-001",
            "origin": "Jakarta",
            "destination": "Bandung",
            "transport_mode": "Road",
        },
        actor=user,
    )
    storage = DocumentStorage(str(tmp_path / "vault"))
    key = f"{organization_id}/{shipment['id']}/invoice.pdf"
    source = _pdf()
    size, digest = storage.write(key, io.BytesIO(source), max_bytes=5 * 1024 * 1024)
    stored = operations.create_document_version(
        organization_id=organization_id,
        user=user,
        shipment_id=shipment["id"],
        document_type="COMMERCIAL_INVOICE",
        filename="invoice.pdf",
        mime_type="application/pdf",
        size_bytes=size,
        sha256=digest,
        storage_key=key,
    )
    job = operations.claim_job(worker_id="worker-regression")
    assert job is not None
    assert job["job_type"] == "EXTRACT_DOCUMENT"

    worker = AssuranceWorker()
    worker.repository = operations
    worker.storage = storage
    worker.handle(job)

    context = operations.document_extraction_context(
        organization_id=organization_id,
        document_id=stored["id"],
        version_id=stored["version"]["id"],
    )
    version = context["version"]
    assert version["extraction_status"] in {"EXTRACTED", "NEEDS_REVIEW"}
    assert version["extraction_provider"]
    assert version["extraction_result_json"]
    assert "storage_key" in version
    register_rows = operations.list_documents(
        organization_id=organization_id,
        shipment_id=shipment["id"],
    )
    assert register_rows[0]["extraction_recorded_at"] is not None
    assert register_rows[0]["status"] in {"EXTRACTED", "REVIEW_REQUIRED"}
