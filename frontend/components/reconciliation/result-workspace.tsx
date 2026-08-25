"use client";

import { ArrowsClockwiseIcon as ArrowClockwise, CheckCircleIcon as CheckCircle, MapPinIcon as MapPin, UploadSimpleIcon as UploadSimple, WarningCircleIcon as WarningCircle } from "@phosphor-icons/react";
import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { acknowledgeException, reconcile } from "@/lib/api";
import type {
  DocumentType,
  DocumentField,
  ReconciliationResult,
  ShipmentAssuranceContext,
} from "@/lib/types";

const docLabels: Record<DocumentType, string> = {
  delivery_order: "Delivery Order",
  invoice: "Invoice",
  packing_list: "Packing List",
};
const matrixFields = ["recipient", "destination", "shipment_id", "items"] as const;

function readableField(field: string) {
  return field.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function confidenceTone(value: number) {
  if (value >= 0.85) return "good";
  if (value >= 0.75) return "warn";
  return "bad";
}

function fieldValue(document: ReconciliationResult["documents"][DocumentType], field: string) {
  if (field === "items") {
    return document.items.map((item) => `${item.sku.value ?? "SKU?"} · ${item.quantity.value ?? "?"} unit`).join("; ") || null;
  }
  const value = document[field as keyof typeof document];
  return value && typeof value === "object" && "value" in value ? value.value : null;
}

function fieldConfidence(document: ReconciliationResult["documents"][DocumentType], field: string) {
  if (field === "items") return document.items[0]?.quantity.confidence || 0;
  const value = document[field as keyof typeof document];
  return value && typeof value === "object" && "confidence" in value ? value.confidence : 0;
}

export function ResultWorkspace({
  initialResult,
  files,
  context,
  onReset,
}: {
  initialResult: ReconciliationResult;
  files: Record<DocumentType, File>;
  context: ShipmentAssuranceContext;
  onReset: () => void;
}) {
  const [result, setResult] = useState(initialResult);
  const [currentFiles, setCurrentFiles] = useState(files);
  const [resolutionReason, setResolutionReason] = useState("");
  const [selectedDocument, setSelectedDocument] = useState<DocumentType>("delivery_order");
  const recheck = useMutation({
    mutationFn: () => reconcile(currentFiles, context),
    onSuccess: (data) => {
      setResult(data);
      toast.success("Shipment berhasil diperiksa kembali");
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const acknowledge = useMutation({
    mutationFn: () => acknowledgeException(result.session_id, resolutionReason),
    onSuccess: (data) => {
      setResult(data);
      toast.success("Catatan resolusi tersimpan pada audit");
      setResolutionReason("");
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const effectiveStatus = result.audit.final_decision || result.effective_status || result.status;
  const geo = result.geographic;
  const hasMapPoints = Boolean(geo?.expected_destination || Object.keys(geo?.document_destinations || {}).length);
  const mapUrl = useMemo(() => {
    const points = [
      geo?.expected_destination,
      ...Object.values(geo?.document_destinations || {}),
    ].filter(Boolean) as Array<{ latitude: number; longitude: number }>;
    if (!points.length) return null;
    const lats = points.map((point) => point.latitude);
    const lngs = points.map((point) => point.longitude);
    const pad = 0.05;
    const bbox = `${Math.min(...lngs) - pad},${Math.min(...lats) - pad},${Math.max(...lngs) + pad},${Math.max(...lats) + pad}`;
    const marker = `${points[0].latitude},${points[0].longitude}`;
    return `https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(bbox)}&layer=mapnik&marker=${encodeURIComponent(marker)}`;
  }, [geo]);

  return (
    <div className="assurance-workspace">
      <header className="assurance-result-header">
        <div>
          <div className="assurance-eyebrow">Shipment Assurance Case</div>
          <h1>{result.context?.reference || context.reference}</h1>
          <p>{result.reason}</p>
        </div>
        <div className="assurance-result-header__decision">
          <StatusBadge status={effectiveStatus} />
          <span className="assurance-result-header__meta">{result.processing_ms} ms · {result.mismatches.length} anomaly</span>
        </div>
      </header>

      <section className="assurance-context-strip" aria-label="Shipment context summary">
        <div><span>Origin</span><strong>{context.origin || "Belum diisi"}</strong></div>
        <div><span>Expected destination</span><strong>{context.expected_destination || "Belum diisi"}</strong></div>
        <div><span>Mode</span><strong>{context.shipping_mode || "—"}</strong></div>
        <div><span>Decision basis</span><strong>Evidence + deterministic rules</strong></div>
      </section>

      <section className="assurance-section">
        <div className="assurance-section-heading"><span className="assurance-step-number">03</span><div><h2>AI document understanding</h2><p>Structured evidence, nilai mentah, confidence, dan sumber tetap terlihat.</p></div></div>
        <div className="assurance-doc-grid">
          {(Object.keys(result.documents) as DocumentType[]).map((type) => {
            const document = result.documents[type];
            return <article key={type} className={`assurance-doc-card ${selectedDocument === type ? "is-selected" : ""}`} onClick={() => setSelectedDocument(type)}>
              <div className="assurance-doc-card__heading"><div><span className="assurance-card-kicker">{docLabels[type]}</span><h3>{document.filename}</h3></div><CheckCircle size={19} weight="fill" className="assurance-icon-good" /></div>
              <div className="assurance-doc-card__meta">{document.extraction_provider} · {document.items.length} line item</div>
              <div className="assurance-field-list">
                {(["document_id", "shipment_id", "recipient", "destination"] as const).map((field) => {
                  const value = document[field];
                  return <div key={field} className="assurance-field-row"><span>{readableField(field)}</span><strong>{String(value.value ?? "—")}</strong><em className={`confidence-${confidenceTone(value.confidence)}`}>{Math.round(value.confidence * 100)}%</em></div>;
                })}
              </div>
            </article>;
          })}
        </div>
        <details className="assurance-details" open>
          <summary>Provenance detail: {docLabels[selectedDocument]}</summary>
          <div className="assurance-provenance-grid">
            {(["document_id", "shipment_id", "sender", "recipient", "destination", "document_total"] as const).map((field) => {
              const value = result.documents[selectedDocument][field];
              return <div key={field}><span>{readableField(field)}</span><strong>{String(value.value ?? "—")}</strong><small>raw: {value.raw_value || "—"} · {value.evidence.length} evidence region</small></div>;
            })}
          </div>
        </details>
      </section>

      <section className="assurance-section">
        <div className="assurance-section-heading"><span className="assurance-step-number">04</span><div><h2>Consistency matrix</h2><p>Perbandingan lintas dokumen menggunakan normalized entity dan rule engine deterministik.</p></div></div>
        <div className="assurance-table-wrap"><table className="assurance-table"><thead><tr><th>Field</th>{(Object.keys(result.documents) as DocumentType[]).map((type) => <th key={type}>{docLabels[type]}</th>)}<th>Result</th></tr></thead><tbody>{matrixFields.map((field) => {
          const values = (Object.keys(result.documents) as DocumentType[]).map((type) => fieldValue(result.documents[type], field));
          const mismatch = result.mismatches.some((item) => item.field.startsWith(field) || (field === "items" && item.field.includes("items")));
          const unique = new Set(values.filter((value) => value !== null).map((value) => String(value).toLowerCase())).size;
          const state = mismatch ? "Mismatch" : unique <= 1 ? "Match" : "Review";
          return <tr key={field}><th>{readableField(field)}</th>{(Object.keys(result.documents) as DocumentType[]).map((type) => <td key={type}>{String(fieldValue(result.documents[type], field) ?? "—")}<small>{Math.round(fieldConfidence(result.documents[type], field) * 100)}%</small></td>)}<td><span className={`assurance-matrix-state assurance-matrix-state--${state.toLowerCase()}`}>{state}</span></td></tr>;
        })}</tbody></table></div>
      </section>

      <section className="assurance-section assurance-geo-section">
        <div className="assurance-section-heading"><span className="assurance-step-number">05</span><div><h2>Destination verification</h2><p>Geocoding dilakukan saat request ini dengan fallback konservatif ketika bukti lokasi ambigu.</p></div></div>
        <div className="assurance-geo-grid">
          <div className="assurance-map-panel">
            {hasMapPoints && mapUrl ? <iframe title="Peta verifikasi tujuan OpenStreetMap" src={mapUrl} loading="lazy" /> : <div className="assurance-map-empty"><MapPin size={22} /><span>Koordinat belum tersedia</span><small>Geocoding gagal atau destination belum diisi. Status tetap review.</small></div>}
            <div className="assurance-map-attribution">© OpenStreetMap contributors · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">ODbL attribution</a></div>
          </div>
          <div className="assurance-geo-summary"><div className="assurance-geo-status"><MapPin size={18} /><strong>{geo?.classification?.replaceAll("_", " ") || "GEOCODING UNCERTAIN"}</strong></div><p>{geo?.message || "Destination tidak dapat diverifikasi."}</p>{geo?.distance_km != null && <div className="assurance-distance">Jarak terjauh terdeteksi <strong>{geo.distance_km} km</strong></div>}<dl>{geo?.expected_destination && <div><dt>Expected</dt><dd>{geo.expected_destination.label}</dd></div>}{Object.entries(geo?.document_destinations || {}).map(([type, point]) => <div key={type}><dt>{docLabels[type as DocumentType]}</dt><dd>{point.label}</dd></div>)}</dl></div>
        </div>
      </section>

      <section className="assurance-section assurance-risk-section">
        <div className="assurance-section-heading"><span className="assurance-step-number">06</span><div><h2>Explainable shipment risk</h2><p>Angka final reproducible dan tidak berasal dari output random model.</p></div></div>
        <div className="assurance-risk-layout"><div className={`assurance-risk-score assurance-risk-score--${(result.risk?.level || "LOW").toLowerCase()}`}><strong>{result.risk?.score ?? 0}</strong><span>/ 100</span><em>{result.risk?.level || "LOW"}</em></div><div className="assurance-contributor-list">{result.risk?.contributors.length ? result.risk.contributors.map((item) => <div key={`${item.code}-${item.label}`}><span><strong>{item.label}</strong><small>{item.detail}</small></span><b>+{item.points}</b></div>) : <div className="assurance-empty-line">Tidak ada contributor risiko material.</div>}</div></div>
      </section>

      <section className="assurance-section assurance-resolution-grid">
        <div><div className="assurance-section-heading"><span className="assurance-step-number">07</span><div><h2>Evidence-based explanation</h2><p>{result.explanation?.provider || "evidence-grounded-rules"}</p></div></div><p className="assurance-explanation">{result.explanation?.summary || result.reason}</p>{result.explanation?.possible_causes.length ? <><h3 className="assurance-subheading">Possible causes — perlu diverifikasi</h3><ul>{result.explanation.possible_causes.map((cause) => <li key={cause}>{cause}</li>)}</ul></> : null}</div>
        <div><div className="assurance-section-heading"><span className="assurance-step-number">08</span><div><h2>Recommended resolution</h2><p>Langkah berikutnya untuk menutup discrepancy.</p></div></div><ol className="assurance-action-list">{(result.explanation?.corrective_actions || [result.recommended_action]).map((action) => <li key={action}>{action}</li>)}</ol></div>
      </section>

      <section className="assurance-section assurance-human-resolution">
        <div className="assurance-section-heading"><span className="assurance-step-number">09</span><div><h2>Human resolution & revalidation</h2><p>Ganti dokumen yang dikoreksi, lalu jalankan ulang seluruh pipeline secara synchronous.</p></div></div>
        <div className="assurance-reupload-grid">{(Object.keys(currentFiles) as DocumentType[]).map((type) => <label key={type} className="assurance-reupload"><span>{docLabels[type]}</span><input type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" onChange={(event) => { const file = event.target.files?.[0]; if (file) setCurrentFiles((current) => ({ ...current, [type]: file })); }} /><small><UploadSimple size={15} />{currentFiles[type].name}</small></label>)}</div>
        <div className="assurance-resolution-actions"><Button variant="secondary" onClick={onReset}>Shipment baru</Button><Button variant="primary" onClick={() => recheck.mutate()} disabled={recheck.isPending}>{recheck.isPending ? "Memeriksa ulang…" : <><ArrowClockwise size={16} /> Re-check shipment</>}</Button></div>
        {effectiveStatus !== "CLEAR" && <div className="assurance-acknowledge"><div><strong>Accept exception dengan catatan</strong><span>Catatan operator disimpan pada audit; keputusan sistem tetap terlihat.</span></div><textarea value={resolutionReason} onChange={(event) => setResolutionReason(event.target.value)} placeholder="Contoh: Kuantitas fisik diverifikasi dan menunggu revisi Packing List." maxLength={1000} /><Button variant="secondary" onClick={() => acknowledge.mutate()} disabled={resolutionReason.trim().length < 5 || acknowledge.isPending}>{acknowledge.isPending ? "Menyimpan…" : "Simpan catatan"}</Button></div>}
      </section>

      <footer className="assurance-final-decision"><div><span>Final dispatch decision</span><strong>{effectiveStatus}</strong><small>Keputusan ditentukan rule engine; AI tidak mengotorisasi dispatch.</small></div><div className="assurance-final-decision__icon">{effectiveStatus === "CLEAR" ? <CheckCircle size={28} weight="fill" /> : <WarningCircle size={28} weight="fill" />}</div></footer>
    </div>
  );
}
