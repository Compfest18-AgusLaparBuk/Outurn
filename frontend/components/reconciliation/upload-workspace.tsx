"use client";

import { Banner } from "@cloudflare/kumo/components/banner";
import { Grid, GridItem } from "@cloudflare/kumo/components/grid";
import { Input } from "@cloudflare/kumo/components/input";
import { LayerCard } from "@cloudflare/kumo/components/layer-card";
import { FileTextIcon as FileText, SpinnerGapIcon as SpinnerGap } from "@phosphor-icons/react";
import { useMutation } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ResultWorkspace } from "@/components/reconciliation/result-workspace";
import { ShipmentAssuranceShell } from "@/components/shipment-assurance-shell";
import { UploadSlot } from "@/components/reconciliation/upload-slot";
import { AppSelect } from "@/components/ui/select";
import { reconcile } from "@/lib/api";
import {
  languageSnapshot,
  subscribeToLanguage,
  translate,
  type AppLanguage,
  type LocaleKey,
} from "@/lib/locale";
import type {
  DocumentType,
  ReconciliationResult,
  ShipmentAssuranceContext,
} from "@/lib/types";

type Files = Record<DocumentType, File | null>;
const initialFiles: Files = { delivery_order: null, invoice: null, packing_list: null };
const initialContext: ShipmentAssuranceContext = {
  reference: "",
  origin: "",
  expected_destination: "",
  dispatch_date: "",
  shipping_mode: "Road",
};

export function UploadWorkspace() {
  const language = useSyncExternalStore(
    subscribeToLanguage,
    languageSnapshot,
    () => "id" as AppLanguage,
  );
  const t = (key: LocaleKey) => translate(language, key);
  const [files, setFiles] = useState<Files>(initialFiles);
  const [context, setContext] = useState<ShipmentAssuranceContext>(initialContext);
  const [errors, setErrors] = useState<Partial<Record<DocumentType, string>>>({});
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      reconcile(files as Record<DocumentType, File>, {
        ...context,
        reference: context.reference.trim(),
        origin: context.origin?.trim() || null,
        expected_destination: context.expected_destination?.trim() || null,
        dispatch_date: context.dispatch_date?.trim() || null,
        shipping_mode: context.shipping_mode?.trim() || null,
      }),
    onSuccess: (data) => setResult(data),
    onError: (error: Error) => toast.error(error.message),
  });

  function setFile(type: DocumentType, file: File | null, error: string | null) {
    setFiles((current) => ({ ...current, [type]: file }));
    setErrors((current) => ({ ...current, [type]: error || undefined }));
  }

  const ready =
    context.reference.trim().length >= 2 &&
    Object.values(files).every(Boolean) &&
    !Object.values(errors).some(Boolean);

  if (result) {
    return (
      <ShipmentAssuranceShell currentStage={7}>
        <ResultWorkspace
          initialResult={result}
          files={files as Record<DocumentType, File>}
          context={context}
          onReset={() => {
            setResult(null);
            setFiles(initialFiles);
            setContext(initialContext);
          }}
        />
      </ShipmentAssuranceShell>
    );
  }

  const updateContext =
    (field: keyof ShipmentAssuranceContext) =>
    (event: React.ChangeEvent<HTMLInputElement>) =>
      setContext((current) => ({ ...current, [field]: event.target.value }));

  return (
    <ShipmentAssuranceShell currentStage={0}>
      <main className="shipment-page">
        <header className="shipment-page-header">
          <div className="shipment-page-header__icon" aria-hidden="true"><FileText size={20} /></div>
          <div>
            <span className="shipment-page-header__eyebrow">Outurn shipment assurance</span>
            <h1>Check a shipment before dispatch</h1>
            <p>Give Outurn one shipment. It will read the evidence, compare the documents, verify the destination, and guide the correction path.</p>
          </div>
        </header>

        <LayerCard id="stage-intake" className="shipment-panel">
          <div className="shipment-section-heading">
            <span className="shipment-step-number">01</span>
            <div>
              <h2>Shipment intake</h2>
              <p>Set the small baseline that the assurance check will validate against.</p>
            </div>
          </div>
          <div className="shipment-form-grid">
            <Input label="Shipment reference" value={context.reference} onChange={updateContext("reference")} placeholder="SHP-10291" required description="Used to keep this check traceable." />
            <Input label="Expected origin" value={context.origin || ""} onChange={updateContext("origin")} placeholder="Jakarta" />
            <Input label="Expected destination" value={context.expected_destination || ""} onChange={updateContext("expected_destination")} placeholder="Bandung" description="Use an address or city; map precision follows the evidence." />
            <Input label="Expected dispatch date" type="date" value={context.dispatch_date || ""} onChange={updateContext("dispatch_date")} />
            <AppSelect label="Transport mode" ariaLabel="Transport mode" value={context.shipping_mode || "Road"} onValueChange={(value) => setContext((current) => ({ ...current, shipping_mode: value }))} options={[{ value: "Road", label: "Road" }, { value: "Sea", label: "Sea" }, { value: "Air", label: "Air" }, { value: "Rail", label: "Rail" }]} />
          </div>
        </LayerCard>

        <LayerCard id="stage-documents" className="shipment-panel">
          <div className="shipment-section-heading">
            <span className="shipment-step-number">02</span>
            <div>
              <h2>Document collection</h2>
              <p>Upload one Delivery Order, Invoice, and Packing List. Each file is checked before analysis.</p>
            </div>
          </div>
          <Grid variant="3up" gap="sm">
            <GridItem><UploadSlot label="Delivery Order" hint={t("fileTypes")} file={files.delivery_order} onFile={(file, error) => setFile("delivery_order", file, error)} /></GridItem>
            <GridItem><UploadSlot label="Invoice" hint={t("fileTypes")} file={files.invoice} onFile={(file, error) => setFile("invoice", file, error)} /></GridItem>
            <GridItem><UploadSlot label="Packing List" hint={t("fileTypes")} file={files.packing_list} onFile={(file, error) => setFile("packing_list", file, error)} /></GridItem>
          </Grid>
          <div className="shipment-action-bar">
            <div>
              <strong>{ready ? "Ready to analyze" : "Add the reference and all three documents"}</strong>
              <span>AI extraction, evidence grounding, normalization, reconciliation, geocoding, and deterministic risk scoring run in one request.</span>
            </div>
            <Button variant="primary" disabled={!ready || mutation.isPending} onClick={() => mutation.mutate()}>
              {mutation.isPending ? <><SpinnerGap size={15} className="animate-spin" /> Analyzing…</> : "Analyze shipment"}
            </Button>
          </div>
          {mutation.isPending && <Banner className="shipment-analysis-status" variant="default" size="sm" icon={<SpinnerGap size={15} className="animate-spin" />} title="AI is reading the documents and checking the destination" description="This stays open until the synchronous assurance result is ready." />}
        </LayerCard>
      </main>
    </ShipmentAssuranceShell>
  );
}
