from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import signal
import socket
import time
import uuid
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.domain.jobs import ProcessingJobType
from app.domain.models import DocumentType
from app.repositories.operations import OperationsRepository, validate_webhook_endpoint
from app.services.document_storage import DocumentStorage
from app.services.extraction import ExtractionRouter
from app.services.file_validation import SafeUpload

LOGGER = logging.getLogger("outurn.worker")


def safe_worker_error(exc: Exception) -> str:
    """Return a stable operator message without persisting sensitive exception detail."""
    if isinstance(exc, FileNotFoundError):
        return "The stored document is unavailable for processing."
    if isinstance(exc, socket.gaierror):
        return "The remote integration hostname could not be resolved."
    if isinstance(exc, (OSError, ValueError)):
        return "The document could not be processed safely."
    if isinstance(exc, httpx.TimeoutException):
        return "The remote integration timed out."
    if isinstance(exc, httpx.HTTPError):
        return "The remote integration could not be reached safely."
    return "The processing worker could not complete this job."


class AssuranceWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.repository = OperationsRepository(
            self.settings.database_url,
            auto_create_schema=self.settings.app_env.casefold() != "production",
        )
        self.extractor = ExtractionRouter(self.settings)
        self.storage = DocumentStorage(self.settings.document_storage_root)
        self.worker_id = f"worker-{uuid.uuid4()}"
        self.running = True

    def stop(self, *_args: object) -> None:
        self.running = False

    def handle(self, job: dict[str, object]) -> None:
        payload = json.loads(str(job.get("payload_json") or "{}"))
        job_type = str(job["job_type"])
        if job_type == ProcessingJobType.ASSESS_SHIPMENT.value:
            self.repository.complete_assessment(
                organization_id=str(job["organization_id"]),
                shipment_id=str(payload["shipment_id"]),
            )
        elif job_type == ProcessingJobType.EXTRACT_DOCUMENT.value:
            organization_id = str(job["organization_id"])
            document_id = str(payload["document_id"])
            version_id = str(payload["version_id"])
            context = self.repository.document_extraction_context(
                organization_id=organization_id,
                document_id=document_id,
                version_id=version_id,
            )
            document_type_map = {
                "COMMERCIAL_INVOICE": DocumentType.INVOICE,
                "INVOICE": DocumentType.INVOICE,
                "PACKING_LIST": DocumentType.PACKING_LIST,
                "DELIVERY_ORDER": DocumentType.DELIVERY_ORDER,
            }
            document_type = document_type_map.get(str(context["document_type"]).upper())
            if document_type is None:
                raise ValueError("Unsupported document type for extraction.")
            version = context["version"]
            with self.storage.open(str(version["storage_key"])) as stream:
                data = stream.read()
            if hashlib.sha256(data).hexdigest() != str(version["sha256"]):
                raise RuntimeError("Stored document hash does not match the validated upload.")
            result = asyncio.run(
                self.extractor.extract(
                    SafeUpload(
                        filename=str(version["filename"]),
                        extension=str(version["filename"]).rsplit(".", 1)[-1].lower(),
                        media_type=str(version["mime_type"]),
                        data=data,
                        sha256=str(version["sha256"]),
                    ),
                    document_type,
                )
            )
            self.repository.complete_document_extraction(
                organization_id=organization_id,
                document_id=document_id,
                version_id=version_id,
                result=result,
            )
        elif job_type == ProcessingJobType.SCREEN_PARTY.value:
            # The screening adapter boundary is intentionally explicit. Until a
            # server-side provider connection is configured, the repository
            # records NOT_CONFIGURED/REQUIRES_REVIEW and the release gate stays
            # blocked; missing provider data is never treated as CLEAR.
            self.repository.complete_screening_job(
                organization_id=str(job["organization_id"]),
                payload=payload,
            )
        elif job_type == ProcessingJobType.SEND_WEBHOOK.value:
            self._send_webhook(
                organization_id=str(job["organization_id"]),
                delivery_id=str(payload["delivery_id"]),
            )
        elif job_type == ProcessingJobType.ESCALATE_TASKS.value:
            self.repository.escalate_overdue_tasks(organization_id=str(job["organization_id"]))
        else:
            raise ValueError(f"Unsupported processing job type: {job_type}")

    def _send_webhook(self, *, organization_id: str, delivery_id: str) -> None:
        context = self.repository.webhook_delivery_context(
            organization_id=organization_id, delivery_id=delivery_id
        )
        delivery = context["delivery"]
        subscription = context["subscription"]
        endpoint = validate_webhook_endpoint(
            str(subscription["endpoint"]),
            production=self.settings.app_env.casefold() == "production",
        )
        assert_public_webhook_addresses(endpoint)
        body = json.dumps(
            json.loads(str(delivery["payload_json"])), sort_keys=True, separators=(",", ":")
        )
        timestamp = str(int(time.time()))
        signature = hmac.new(
            context["secret"].encode("utf-8"),
            f"{timestamp}.{body}".encode(),
            hashlib.sha256,
        ).hexdigest()
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False) as client:
                response = client.post(
                    endpoint,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Outurn-Event": str(delivery["event_type"]),
                        "X-Outurn-Delivery": str(delivery["id"]),
                        "X-Outurn-Nonce": str(delivery["id"]),
                        "X-Outurn-Timestamp": timestamp,
                        "X-Outurn-Signature": f"sha256={signature}",
                    },
                )
            if not 200 <= response.status_code < 300:
                raise RuntimeError("Webhook endpoint returned a non-success status.")
        except Exception:
            self.repository.mark_webhook_delivery_retry(
                delivery_id=delivery_id,
                safe_error="Webhook delivery attempt failed safely.",
            )
            raise
        self.repository.finish_webhook_delivery(
            delivery_id=delivery_id,
            success=True,
            response_code=response.status_code,
        )

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.repository.heartbeat(
            worker_id=self.worker_id,
            status="RUNNING",
            version=self.settings.app_version,
        )
        last_webhook_scan = 0.0
        while self.running:
            self.repository.recover_stale_jobs()
            if time.monotonic() - last_webhook_scan >= 10:
                self.repository.enqueue_domain_event_deliveries()
                last_webhook_scan = time.monotonic()
            job = self.repository.claim_job(worker_id=self.worker_id)
            if job is None:
                self.repository.heartbeat(
                    worker_id=self.worker_id,
                    status="IDLE",
                    version=self.settings.app_version,
                )
                time.sleep(self.settings.worker_poll_interval_seconds)
                continue
            self.repository.heartbeat(
                worker_id=self.worker_id,
                status="PROCESSING",
                version=self.settings.app_version,
                current_job_id=str(job["id"]),
            )
            try:
                self.handle(job)
            except Exception as exc:  # keep the worker alive and persist only safe error text
                safe_error = safe_worker_error(exc)
                LOGGER.exception("Processing job failed: %s", job["id"])
                self.repository.finish_job(
                    job_id=str(job["id"]),
                    success=False,
                    error_code="WORKER_HANDLER_FAILED",
                    safe_error=safe_error,
                )
                self.repository.heartbeat(
                    worker_id=self.worker_id,
                    status="DEGRADED",
                    version=self.settings.app_version,
                    safe_error=safe_error,
                )
            else:
                self.repository.finish_job(job_id=str(job["id"]), success=True)
                self.repository.heartbeat(
                    worker_id=self.worker_id,
                    status="RUNNING",
                    version=self.settings.app_version,
                )


def url_host(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        raise ValueError("Webhook endpoint has no hostname.")
    return parsed.hostname


def assert_public_webhook_addresses(endpoint: str) -> None:
    """Reject every resolved address that is not globally routable.

    Resolving all A/AAAA records at dispatch time closes the common gap where
    creation-time validation checks a public hostname but the worker later
    follows a private DNS answer. The HTTP client also has redirects disabled.
    """
    parsed = urlparse(endpoint)
    host = url_host(endpoint)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    if not addresses:
        raise socket.gaierror(f"No address records for {host}")
    if any(not address.is_global for address in addresses):
        raise ValueError("Webhook endpoint resolved to a non-public address.")


def main() -> None:
    AssuranceWorker().run()


if __name__ == "__main__":
    main()
