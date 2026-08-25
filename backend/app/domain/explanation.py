from __future__ import annotations

from app.domain.models import (
    GeoClassification,
    GeographicValidation,
    Mismatch,
    MismatchType,
    RootCauseExplanation,
)


def explain_findings(
    mismatches: list[Mismatch], geographic: GeographicValidation
) -> RootCauseExplanation:
    if not mismatches and geographic.classification == GeoClassification.GEOGRAPHIC_MATCH:
        return RootCauseExplanation(
            summary=(
                "Dokumen shipment konsisten dan tujuan dokumen berada pada area "
                "operasional yang sama."
            ),
            possible_causes=[],
            evidence_basis=[
                "Seluruh field kritis dan line item lolos rule rekonsiliasi.",
                geographic.message,
            ],
            corrective_actions=[
                "Simpan hasil pemeriksaan sebagai bukti pre-dispatch.",
                "Lanjutkan dispatch sesuai prosedur gudang.",
            ],
            provider="evidence-grounded-rules",
        )

    summaries = [item.explanation for item in mismatches]
    causes: list[str] = []
    actions: list[str] = [
        "Verifikasi dokumen dan kondisi fisik shipment sebelum dispatch.",
        "Perbaiki atau unggah ulang dokumen yang menjadi sumber discrepancy.",
        "Jalankan pemeriksaan kembali setelah koreksi.",
    ]
    for mismatch in mismatches:
        if mismatch.type == MismatchType.QUANTITY_MISMATCH:
            causes.extend(["Possible partial packing.", "Packing List mungkin belum diperbarui."])
            actions.insert(1, "Bandingkan kuantitas fisik dengan SKU yang disorot.")
        elif mismatch.type in {
            MismatchType.WRONG_DESTINATION,
            MismatchType.POSSIBLE_TEXT_VARIATION,
        }:
            causes.append("Variasi penulisan alamat atau versi dokumen berbeda perlu diverifikasi.")
        elif mismatch.type == MismatchType.LOW_CONFIDENCE_EXTRACTION:
            causes.append("Bukti pada dokumen mungkin tidak terbaca lengkap oleh extractor.")
        elif mismatch.type == MismatchType.WRONG_RECIPIENT:
            actions.insert(1, "Konfirmasi recipient terhadap order atau referensi pengiriman.")

    if geographic.classification != GeoClassification.GEOGRAPHIC_MATCH:
        summaries.append(geographic.message)
        causes.append(
            "Resolusi geografis ambigu atau tujuan dokumen berbeda; jangan menganggap "
            "ini fraud tanpa verifikasi."
        )

    return RootCauseExplanation(
        summary=" ".join(summaries) or "Evidence shipment membutuhkan pemeriksaan manusia.",
        possible_causes=list(dict.fromkeys(causes)),
        evidence_basis=summaries,
        corrective_actions=list(dict.fromkeys(actions)),
        provider="evidence-grounded-rules",
    )
