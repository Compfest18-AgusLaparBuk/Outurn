"use client";

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
import { languageSnapshot, subscribeToLanguage, translate, type AppLanguage, type LocaleKey } from "@/lib/locale";
import type { DocumentType, ReconciliationResult } from "@/lib/types";

type Files = Record<DocumentType, File | null>;
const initialFiles: Files = { delivery_order: null, invoice: null, packing_list: null };

export function UploadWorkspace() {
  const language = useSyncExternalStore(subscribeToLanguage, languageSnapshot, () => "id" as AppLanguage);
  const t = (key: LocaleKey) => translate(language, key);
  const [files, setFiles] = useState<Files>(initialFiles);
  const [errors, setErrors] = useState<Partial<Record<DocumentType, string>>>({});
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const mutation = useMutation({ mutationFn: () => reconcile(files as Record<DocumentType, File>), onSuccess: (data) => setResult(data), onError: (error: Error) => toast.error(error.message) });
  function setFile(type: DocumentType, file: File | null, error: string | null) { setFiles((current) => ({ ...current, [type]: file })); setErrors((current) => ({ ...current, [type]: error || undefined })); }
  const ready = Object.values(files).every(Boolean) && !Object.values(errors).some(Boolean);
  if (result) return <ResultWorkspace initialResult={result} files={files as Record<DocumentType, File>} onReset={() => { setResult(null); setFiles(initialFiles); }} />;
  return (
    <CloudflarePageShell className="cf-document-check-page">
      <PageHeader
        icon={FileText}
        title={t("checkShipmentDocuments")}
        description={t("checkShipmentDescription")}
      />
      <section className="document-check-page" aria-label="Dokumen shipment">
        <div className="grid gap-3 md:grid-cols-3">
          <UploadSlot
            label={t("deliveryOrder")}
            hint={t("fileTypes")}
            file={files.delivery_order}
            onFile={(file, error) => setFile("delivery_order", file, error)}
          />
          <UploadSlot
            label="Invoice"
            hint={t("fileTypes")}
            file={files.invoice}
            onFile={(file, error) => setFile("invoice", file, error)}
          />
          <UploadSlot
            label={t("packingList")}
            hint={t("fileTypes")}
            file={files.packing_list}
            onFile={(file, error) => setFile("packing_list", file, error)}
          />
        </div>
        <section className="document-check-action">
          <div>
            <div className="cf-section-title">
              {ready ? t("documentsReady") : t("addAllDocuments")}
            </div>
            <div className="cf-data-surface__description">
              {t("uploadCompareReview")}
            </div>
          </div>
          <Button
            variant="primary"
            disabled={!ready || mutation.isPending}
            onClick={() => mutation.mutate()}
            className="min-w-44"
          >
            {mutation.isPending ? (
              <>
                <SpinnerGap size={15} className="animate-spin" />
                {t("checkingDocuments")}
              </>
            ) : (
              t("checkDocuments")
            )}
          </Button>
        </section>
        {mutation.isPending && (
          <div className="document-check-status" role="status">
            {t("readingDocuments")}
          </div>
        )}
      </section>
    </CloudflarePageShell>
  );
}
