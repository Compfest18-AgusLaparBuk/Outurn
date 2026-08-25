"use client";

import { Banner } from "@cloudflare/kumo/components/banner";
import { Grid, GridItem } from "@cloudflare/kumo/components/grid";
import { FileTextIcon as FileText, SpinnerGapIcon as SpinnerGap } from "@phosphor-icons/react";
import { useMutation } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ResultWorkspace } from "@/components/reconciliation/result-workspace";
import { UploadSlot } from "@/components/reconciliation/upload-slot";
import { PageHeader } from "@/components/ui/page-header";
import { CloudflarePageShell } from "@/components/ui/page-primitives";
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
    );
  }

  const updateContext =
    (field: keyof ShipmentAssuranceContext) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setContext((current) => ({ ...current, [field]: event.target.value }));

  return (
    <CloudflarePageShell className="cf-document-check-page">
      <PageHeader
        icon={FileText}
        title="Shipment Assurance Workspace"
        description="Baca tiga dokumen, telusuri evidence AI, selesaikan discrepancy, lalu pastikan shipment layak dilepas sebelum dispatch."
      />
      <section className="assurance-intake" aria-label="Konteks shipment">
        <div className="assurance-step-heading">
          <span className="assurance-step-number">01</span>
          <div>
            <h2>Konteks shipment</h2>
            <p>Informasi ini menjadi anchor pemeriksaan dokumen dan tujuan.</p>
          </div>
        </div>
        <div className="form-grid">
          <label>
            Referensi shipment <span className="field-required">*</span>
            <input value={context.reference} onChange={updateContext("reference")} placeholder="SHP-10291" required />
          </label>
          <label>
            Asal / origin <span className="field-optional">opsional</span>
            <input value={context.origin || ""} onChange={updateContext("origin")} placeholder="Gudang Bandung" />
          </label>
          <label>
            Expected destination <span className="field-optional">opsional</span>
            <input value={context.expected_destination || ""} onChange={updateContext("expected_destination")} placeholder="Jl. Soekarno Hatta 25, Bandung" />
          </label>
          <label>
            Dispatch date <span className="field-optional">opsional</span>
            <input type="date" value={context.dispatch_date || ""} onChange={updateContext("dispatch_date")} />
          </label>
          <label>
            Shipping mode
            <select value={context.shipping_mode || "Road"} onChange={updateContext("shipping_mode")}>
              <option value="Road">Road</option>
              <option value="Sea">Sea</option>
              <option value="Air">Air</option>
              <option value="Rail">Rail</option>
            </select>
          </label>
        </div>
      </section>

      <section className="document-check-page" aria-label="Input dokumen">
        <div className="assurance-step-heading">
          <span className="assurance-step-number">02</span>
          <div>
            <h2>Dokumen wajib</h2>
            <p>Unggah Invoice, Packing List, dan Delivery Order dalam satu case.</p>
          </div>
        </div>
        <Grid variant="3up" gap="sm">
          <GridItem>
            <UploadSlot label="Delivery Order" hint={t("fileTypes")} file={files.delivery_order} onFile={(file, error) => setFile("delivery_order", file, error)} />
          </GridItem>
          <GridItem>
            <UploadSlot label="Invoice" hint={t("fileTypes")} file={files.invoice} onFile={(file, error) => setFile("invoice", file, error)} />
          </GridItem>
          <GridItem>
            <UploadSlot label="Packing List" hint={t("fileTypes")} file={files.packing_list} onFile={(file, error) => setFile("packing_list", file, error)} />
          </GridItem>
        </Grid>
        <section className="document-check-action">
          <div>
            <div className="cf-section-title">{ready ? "Semua evidence siap dianalisis" : "Lengkapi konteks dan tiga dokumen"}</div>
            <div className="cf-data-surface__description">Proses AI, normalisasi, rekonsiliasi, geocoding, dan risk scoring berjalan dalam satu request.</div>
          </div>
          <Button variant="primary" disabled={!ready || mutation.isPending} onClick={() => mutation.mutate()} className="min-w-44">
            {mutation.isPending ? <><SpinnerGap size={15} className="animate-spin" /> Menganalisis…</> : "Analisis shipment"}
          </Button>
        </section>
        {mutation.isPending && <Banner className="document-check-status" variant="default" size="sm" icon={<SpinnerGap size={15} className="animate-spin" />} title="AI sedang membaca evidence dan memeriksa tujuan…" />}
      </section>
    </CloudflarePageShell>
  );
}
