"use client";

import { Badge } from "@cloudflare/kumo/components/badge";
import { InputArea } from "@cloudflare/kumo/components/input";
import { LayerCard } from "@cloudflare/kumo/components/layer-card";
import { Switch } from "@cloudflare/kumo/components/switch";
import { Table } from "@cloudflare/kumo/components/table";
import {
  ArrowsClockwiseIcon as ArrowClockwise,
  CheckCircleIcon as CheckCircle,
  MapPinIcon as MapPin,
  WarningCircleIcon as WarningCircle,
} from "@phosphor-icons/react";
import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { UploadSlot } from "@/components/reconciliation/upload-slot";
import { reconcile } from "@/lib/api";
import type {
  DocumentType,
  ReconciliationResult,
  ShipmentAssuranceContext,
} from "@/lib/types";

const docLabels: Record<DocumentType, string> = {
  delivery_order: "Delivery Order",
  invoice: "Invoice",
  packing_list: "Packing List",
};

const matrixFields = ["recipient", "destination", "shipment_id", "items"] as const;
const evidenceFields = [
  "document_id",
  "shipment_id",
  "sender",
  "recipient",
  "destination",
  "document_total",
] as const;

function readableField(field: string) {
  return field.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function fieldValue(
  document: ReconciliationResult["documents"][DocumentType],
  field: string,
) {
  if (field === "items") {
    return (
      document.items
        .map((item) => `${item.sku.value ?? "SKU?"} · ${item.quantity.value ?? "?"} unit`)
        .join("; ") || null
    );
  }
  const value = document[field as keyof typeof document];
  return value && typeof value === "object" && "value" in value ? value.value : null;
}

function fieldConfidence(
  document: ReconciliationResult["documents"][DocumentType],
  field: string,
) {
  if (field === "items") return document.items[0]?.quantity.confidence || 0;
  const value = document[field as keyof typeof document];
  return value && typeof value === "object" && "confidence" in value ? value.confidence : 0;
}

function badgeVariant(state: string) {
  if (state === "Match") return "success" as const;
  if (state === "Mismatch") return "error" as const;
  return "warning" as const;
}

function decisionLabel(status: string) {
  if (status === "CLEAR") return "Clear for dispatch";
  if (status === "HOLD") return "Hold before dispatch";
  return "Review before dispatch";
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
  const [previousResult, setPreviousResult] = useState<ReconciliationResult | null>(null);
  const [currentFiles, setCurrentFiles] = useState<Record<DocumentType, File | null>>(files);
  const [selectedDocument, setSelectedDocument] = useState<DocumentType>("delivery_order");
  const [showEvidence, setShowEvidence] = useState(false);
  const [resolutionNote, setResolutionNote] = useState("");
  const [savedNote, setSavedNote] = useState("");
  const documentTypes = Object.keys(result.documents) as DocumentType[];
  const effectiveStatus = result.audit.final_decision || result.effective_status || result.status;
  const geo = result.geographic;
  const hasMapPoints = Boolean(geo?.expected_destination || Object.keys(geo?.document_destinations || {}).length);

  const recheck = useMutation({
    mutationFn: () => {
      if (Object.values(currentFiles).some((file) => !file)) {
        throw new Error("Upload all three documents before running the re-check.");
      }
      return reconcile(currentFiles as Record<DocumentType, File>, context);
    },
    onMutate: () => setPreviousResult(result),
    onSuccess: (data) => {
      setResult(data);
      toast.success("Shipment checked again");
    },
    onError: (error: Error) => {
      setPreviousResult(null);
      toast.error(error.message);
    },
  });

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
    return `https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(bbox)}&layer=mapnik&marker=${encodeURIComponent(`${points[0].latitude},${points[0].longitude}`)}`;
  }, [geo]);

  const selected = result.documents[selectedDocument];
  const selectedFields = evidenceFields.map((field) => ({ field, value: selected[field] }));
  const beforeQuantity = previousResult?.documents.packing_list.items[0]?.quantity.value ?? "—";
  const afterQuantity = result.documents.packing_list.items[0]?.quantity.value ?? "—";

  return (
    <main className="shipment-page shipment-result">
      <header className="shipment-result-header">
        <div>
          <span className="shipment-page-header__eyebrow">Current shipment assurance</span>
          <h1>{result.context?.reference || context.reference}</h1>
          <p>{result.reason}</p>
        </div>
        <div className="shipment-result-header__decision">
          <StatusBadge status={effectiveStatus} />
          <span>{result.processing_ms} ms · {result.mismatches.length} anomaly</span>
        </div>
      </header>

      <div className="shipment-summary-grid" aria-label="Shipment summary">
        <div><span>Origin</span><strong>{context.origin || "Not provided"}</strong></div>
        <div><span>Expected destination</span><strong>{context.expected_destination || "Not provided"}</strong></div>
        <div><span>Transport mode</span><strong>{context.shipping_mode || "—"}</strong></div>
        <div><span>Decision basis</span><strong>Evidence + deterministic rules</strong></div>
      </div>

      <LayerCard id="stage-evidence" className="shipment-panel">
        <div className="shipment-section-heading"><span className="shipment-step-number">03</span><div><h2>AI document understanding</h2><p>Every critical field keeps its value, confidence, source, and evidence count visible.</p></div></div>
        <div className="shipment-document-tabs" role="tablist" aria-label="Documents">
          {documentTypes.map((type) => {
            const document = result.documents[type];
            const active = selectedDocument === type;
            return <Button key={type} type="button" variant={active ? "primary" : "secondary"} className="shipment-document-tab" aria-pressed={active} onClick={() => setSelectedDocument(type)}><span><strong>{docLabels[type]}</strong><small>{document.filename}</small></span><Badge variant="success" appearance="dot">{Math.round(document.document_type_confidence * 100)}%</Badge></Button>;
          })}
        </div>
        <div className="shipment-evidence-toolbar"><span>{selected.extraction_provider} · {selected.items.length} line item</span><Switch label="Show evidence details" checked={showEvidence} onCheckedChange={setShowEvidence} size="sm" /></div>
        <Table className="shipment-table">
          <Table.Header><Table.Row><Table.Head>Field</Table.Head><Table.Head>Value</Table.Head><Table.Head>Confidence</Table.Head><Table.Head>Source</Table.Head></Table.Row></Table.Header>
          <Table.Body>{selectedFields.map(({ field, value }) => <Table.Row key={field}><Table.Cell>{readableField(field)}</Table.Cell><Table.Cell><strong>{String(value.value ?? "—")}</strong>{showEvidence && <small className="shipment-table__subvalue">Raw: {value.raw_value || "—"}</small>}</Table.Cell><Table.Cell><Badge variant={value.confidence >= 0.85 ? "success" : value.confidence >= 0.75 ? "warning" : "error"}>{Math.round(value.confidence * 100)}%</Badge></Table.Cell><Table.Cell>{showEvidence ? `${value.source} · ${value.evidence.length} region${value.evidence.length === 1 ? "" : "s"}` : value.source}</Table.Cell></Table.Row>)}</Table.Body>
        </Table>
      </LayerCard>

      <LayerCard id="stage-reconciliation" className="shipment-panel">
        <div className="shipment-section-heading"><span className="shipment-step-number">04</span><div><h2>Cross-document reconciliation</h2><p>Semantic normalization is visible, while the operational result stays deterministic.</p></div></div>
        <div className="shipment-table-scroll"><Table className="shipment-table shipment-table--matrix"><Table.Header><Table.Row><Table.Head>Attribute</Table.Head>{documentTypes.map((type) => <Table.Head key={type}>{docLabels[type]}</Table.Head>)}<Table.Head>Result</Table.Head></Table.Row></Table.Header><Table.Body>{matrixFields.map((field) => { const values = documentTypes.map((type) => fieldValue(result.documents[type], field)); const mismatch = result.mismatches.some((item) => item.field.startsWith(field) || (field === "items" && item.field.includes("items"))); const unique = new Set(values.filter((value) => value !== null).map((value) => String(value).toLowerCase())).size; const state = mismatch ? "Mismatch" : unique <= 1 ? "Match" : "Review"; return <Table.Row key={field}><Table.Cell><strong>{readableField(field)}</strong></Table.Cell>{documentTypes.map((type) => <Table.Cell key={type}>{String(fieldValue(result.documents[type], field) ?? "—")}<small className="shipment-table__subvalue">{Math.round(fieldConfidence(result.documents[type], field) * 100)}% confidence</small></Table.Cell>)}<Table.Cell><Badge variant={badgeVariant(state)}>{state}</Badge></Table.Cell></Table.Row>; })}</Table.Body></Table></div>
      </LayerCard>

      <LayerCard id="stage-destination" className="shipment-panel">
        <div className="shipment-section-heading"><span className="shipment-step-number">05</span><div><h2>Destination verification</h2><p>OpenStreetMap is used as a validation aid; uncertain geocoding never becomes a clear decision.</p></div></div>
        <div className="shipment-geo-grid"><div className="shipment-map-panel">{hasMapPoints && mapUrl ? <iframe title="OpenStreetMap destination verification" src={mapUrl} loading="eager" /> : <div className="shipment-map-empty"><MapPin size={24} /><strong>Coordinates unavailable</strong><span>Geocoding failed or the destination is too broad to resolve safely.</span></div>}<div className="shipment-map-attribution">© OpenStreetMap contributors · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">ODbL attribution</a></div></div><div className="shipment-geo-summary"><div className="shipment-geo-summary__status"><MapPin size={18} /><strong>{geo?.classification?.replaceAll("_", " ") || "GEOCODING UNCERTAIN"}</strong></div><p>{geo?.message || "Destination could not be verified."}</p>{geo?.distance_km != null && <div className="shipment-highlight">Farthest resolved distance <strong>{geo.distance_km} km</strong></div>}<dl>{geo?.expected_destination && <div><dt>Expected</dt><dd>{geo.expected_destination.label}</dd></div>}{Object.entries(geo?.document_destinations || {}).map(([type, point]) => <div key={type}><dt>{docLabels[type as DocumentType]}</dt><dd>{point.label}</dd></div>)}</dl></div></div>
      </LayerCard>

      <LayerCard id="stage-risk" className="shipment-panel">
        <div className="shipment-section-heading"><span className="shipment-step-number">06</span><div><h2>Explainable shipment risk</h2><p>The score is reproducible and calculated outside the AI provider.</p></div></div>
        <div className="shipment-risk-layout"><div className={`shipment-risk-score shipment-risk-score--${(result.risk?.level || "LOW").toLowerCase()}`}><strong>{result.risk?.score ?? 0}</strong><span>/ 100</span><Badge variant={effectiveStatus === "CLEAR" ? "success" : effectiveStatus === "HOLD" ? "error" : "warning"}>{result.risk?.level || "LOW"}</Badge></div><div className="shipment-contributor-list">{result.risk?.contributors.length ? result.risk.contributors.map((item, index) => <div key={`${item.code}-${item.label}-${index}`}><span><strong>{item.label}</strong><small>{item.detail}</small></span><b>+{item.points}</b></div>) : <div className="shipment-empty-line">No material risk contributors.</div>}</div></div>
      </LayerCard>

      <LayerCard id="stage-resolution" className="shipment-panel">
        <div className="shipment-section-heading"><span className="shipment-step-number">07</span><div><h2>Explain, correct, and re-check</h2><p>{result.explanation?.provider || "Evidence-grounded explanation"} turns the detected anomaly into a concrete operator path.</p></div></div>
        <div className="shipment-resolution-grid"><div><h3>What may be happening</h3><p className="shipment-explanation">{result.explanation?.summary || result.reason}</p>{result.explanation?.possible_causes.length ? <ul>{result.explanation.possible_causes.map((cause) => <li key={cause}>{cause}</li>)}</ul> : <p className="shipment-muted">No unresolved explanation remains.</p>}</div><div><h3>Recommended actions</h3><ol>{(result.explanation?.corrective_actions || [result.recommended_action]).map((action) => <li key={action}>{action}</li>)}</ol></div></div>
        <div className="shipment-reupload-heading"><div><h3>Replace a corrected document</h3><p>Only this shipment case is rechecked. No background worker or queue is involved.</p></div><Badge variant="info">Synchronous</Badge></div>
        <div className="shipment-reupload-grid">{documentTypes.map((type) => <UploadSlot key={type} label={`Replace ${docLabels[type]}`} hint="PDF, JPEG, or PNG" file={currentFiles[type]} onFile={(file) => setCurrentFiles((current) => ({ ...current, [type]: file }))} />)}</div>
        <div className="shipment-action-bar shipment-action-bar--end"><Button variant="secondary" onClick={onReset}>New shipment check</Button><Button variant="primary" onClick={() => recheck.mutate()} disabled={recheck.isPending || Object.values(currentFiles).some((file) => !file)}>{recheck.isPending ? <><ArrowClockwise size={16} className="animate-spin" /> Re-checking…</> : <><ArrowClockwise size={16} /> Re-check shipment</>}</Button></div>
        {effectiveStatus !== "CLEAR" && <div className="shipment-operator-note"><InputArea label="Operator resolution note" value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} placeholder="Example: physical quantity verified; corrected Packing List uploaded." description="Saved locally for this case; it does not override the deterministic decision." minLength={5} maxLength={1000} /><Button variant="secondary" onClick={() => setSavedNote(resolutionNote.trim())} disabled={resolutionNote.trim().length < 5}>Save note</Button>{savedNote && <Badge variant="success">Note saved for this case</Badge>}</div>}
      </LayerCard>

      {previousResult && <LayerCard className="shipment-panel" aria-label="Before and after verification"><div className="shipment-section-heading"><span className="shipment-step-number">08</span><div><h2>What changed?</h2><p>The previous result stays beside the new result so the correction is verifiable.</p></div></div><Table className="shipment-table"><Table.Header><Table.Row><Table.Head>Check</Table.Head><Table.Head>Before</Table.Head><Table.Head>After</Table.Head></Table.Row></Table.Header><Table.Body><Table.Row><Table.Cell>Quantity</Table.Cell><Table.Cell>{String(beforeQuantity)}</Table.Cell><Table.Cell>{String(afterQuantity)}</Table.Cell></Table.Row><Table.Row><Table.Cell>Destination</Table.Cell><Table.Cell>{previousResult.geographic?.classification?.replaceAll("_", " ") || "—"}</Table.Cell><Table.Cell>{geo?.classification?.replaceAll("_", " ") || "—"}</Table.Cell></Table.Row><Table.Row><Table.Cell>Risk</Table.Cell><Table.Cell>{previousResult.risk?.score ?? "—"} · {previousResult.risk?.level || "—"}</Table.Cell><Table.Cell>{result.risk?.score ?? "—"} · {result.risk?.level || "—"}</Table.Cell></Table.Row><Table.Row><Table.Cell>Decision</Table.Cell><Table.Cell><StatusBadge status={previousResult.effective_status || previousResult.status} /></Table.Cell><Table.Cell><StatusBadge status={effectiveStatus} /></Table.Cell></Table.Row></Table.Body></Table></LayerCard>}

      <LayerCard id="stage-final-decision" className={`shipment-final-decision shipment-final-decision--${effectiveStatus.toLowerCase()}`}><div><span>Final dispatch decision</span><h2>{decisionLabel(effectiveStatus)}</h2><p>AI explains and grounds the evidence. The deterministic rule engine owns CLEAR, REVIEW, and HOLD.</p></div><div className="shipment-final-decision__icon" aria-hidden="true">{effectiveStatus === "CLEAR" ? <CheckCircle size={30} weight="fill" /> : <WarningCircle size={30} weight="fill" />}</div></LayerCard>
    </main>
  );
}
