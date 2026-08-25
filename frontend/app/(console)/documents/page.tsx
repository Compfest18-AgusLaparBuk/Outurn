"use client";

import { Dialog, DialogRoot } from "@cloudflare/kumo/components/dialog";
import { Input } from "@cloudflare/kumo/components/input";
import { Table } from "@cloudflare/kumo/components/table";
import {
  FileArrowUpIcon as FileArrowUp,
  PlusIcon as Plus,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useDeferredValue, useEffect, useRef, useState } from "react";
import { ActionLink, Button } from "@/components/ui/button";
import {
  OperationalState,
  StateNotice,
} from "@/components/ui/operational-primitives";
import { PageHeader } from "@/components/ui/page-header";
import {
  CloudflarePageShell,
  DataTableSurface,
  EmptyState,
  FilterBar,
  LoadingState,
  SearchField,
} from "@/components/ui/page-primitives";
import { AppSelect } from "@/components/ui/select";
import { fetchOperationsList, fetchShipments, uploadDocument } from "@/lib/api";

type Row = Record<string, unknown>;
const documentTypes = [
  { value: "", label: "Semua jenis" },
  { value: "COMMERCIAL_INVOICE", label: "Invoice" },
  { value: "PACKING_LIST", label: "Daftar kemasan" },
  { value: "DELIVERY_ORDER", label: "Surat jalan" },
  { value: "CERTIFICATE_OF_ORIGIN", label: "Sertifikat asal" },
];
function date(value: unknown) {
  return value ? new Date(String(value)).toLocaleString("id-ID") : "—";
}
function version(row: Row) {
  const value = row.version as Row | undefined;
  return value ? `v${String(value.version || "—")}` : "—";
}
function extraction(row: Row) {
  const value = row.version as Row | undefined;
  try {
    return JSON.parse(String(value?.extraction_result_json || "{}")) as Row;
  } catch {
    return {};
  }
}
function confidence(row: Row) {
  const value = row.version as Row | undefined;
  const raw = value?.extraction_confidence;
  return typeof raw === "number" ? `${Math.round(raw * 100)}%` : "—";
}
function providerParts(value: unknown) {
  const [provider = "—", model = "—"] = String(value || "—").split(":", 2);
  return { provider, model };
}
function ExtractionDetail({ row, onClose }: { row: Row; onClose: () => void }) {
  const versionData = row.version as Row | undefined;
  const result = extraction(row);
  const provider = providerParts(versionData?.extraction_provider);
  const fields = [
    "document_id",
    "shipment_id",
    "sender",
    "recipient",
    "destination",
    "document_total",
  ].map((name) => [name, result[name] as Row | undefined] as const);
  const needsReview =
    String(versionData?.extraction_status) === "NEEDS_REVIEW" ||
    String(row.status) === "REVIEW_REQUIRED";
  return (
    <DialogRoot
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog className="cf-extraction-detail-dialog">
        <Dialog.Title>Asal-usul hasil ekstraksi</Dialog.Title>
        <Dialog.Description>
          Output AI/OCR adalah evidence probabilistik. Compliance dan release
          tetap ditentukan oleh rule serta review manusia.
        </Dialog.Description>
        <dl className="cf-extraction-provenance">
          <div>
            <dt>Provider</dt>
            <dd>{provider.provider}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{provider.model}</dd>
          </div>
          <div>
            <dt>Dicatat pada</dt>
            <dd>{date(row.extraction_recorded_at)}</dd>
          </div>
          <div>
            <dt>Confidence minimum</dt>
            <dd>{confidence(row)}</dd>
          </div>
          <div>
            <dt>Peninjauan manusia</dt>
            <dd>
              <OperationalState
                value={
                  needsReview
                    ? "REVIEW_REQUIRED"
                    : String(row.status || "PENDING")
                }
              />
            </dd>
          </div>
          <div>
            <dt>Versi dokumen</dt>
            <dd>{version(row)}</dd>
          </div>
        </dl>
        {needsReview ? (
          <StateNotice title="Hasil ekstraksi perlu ditinjau" tone="warning">
            Confidence rendah, klasifikasi tidak jelas, atau line item belum
            lengkap. Output ini tidak dapat membuat keputusan CLEAR secara
            otomatis.
          </StateNotice>
        ) : (
          <StateNotice
            title="Hasil ekstraksi terpisah dari kepatuhan"
            tone="info"
          >
            Status ekstraksi bukan keputusan release. Rule deterministik dan
            review yang menentukan hasil assurance.
          </StateNotice>
        )}
        <section className="cf-extraction-fields">
          <div>
            <h2 className="cf-section-title">Nilai dan evidence</h2>
            <p className="cf-metadata">
              Nilai normalisasi, nilai asli, serta area bukti yang tersimpan
              dari hasil ekstraksi.
            </p>
          </div>
          {fields.map(([name, field]) => (
            <article key={name}>
              <h3>{name.replaceAll("_", " ")}</h3>
              <dl>
                <div>
                  <dt>Nilai normalisasi</dt>
                  <dd>{field?.value == null ? "—" : String(field.value)}</dd>
                </div>
                <div>
                  <dt>Nilai asli</dt>
                  <dd>
                    {field?.raw_value == null ? "—" : String(field.raw_value)}
                  </dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>
                    {typeof field?.confidence === "number"
                      ? `${Math.round(field.confidence * 100)}%`
                      : "—"}
                  </dd>
                </div>
              </dl>
              <pre>{JSON.stringify(field?.evidence || [], null, 2)}</pre>
            </article>
          ))}
        </section>
        <div className="form-panel__actions">
          <Button variant="secondary" onClick={onClose}>
            Tutup
          </Button>
        </div>
      </Dialog>
    </DialogRoot>
  );
}

export default function DocumentsPage() {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [documentTypeFilter, setDocumentTypeFilter] = useState("");
  const [shipmentId, setShipmentId] = useState("");
  const [documentType, setDocumentType] = useState("COMMERCIAL_INVOICE");
  const [file, setFile] = useState<File | null>(null);
  const deferredQuery = useDeferredValue(query);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    function closeOnOutsidePointerDown(event: PointerEvent) {
      const target = event.target;
      const dialog = document.querySelector(".cf-document-upload-dialog");
      const inListbox =
        target instanceof Element &&
        Boolean(target.closest('[role="listbox"], [role="option"]'));
      if (
        dialog &&
        target instanceof Node &&
        !dialog.contains(target) &&
        !inListbox
      )
        setOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutsidePointerDown, true);
    return () =>
      document.removeEventListener(
        "pointerdown",
        closeOnOutsidePointerDown,
        true,
      );
  }, [open]);
  const shipments = useQuery({
    queryKey: ["shipments", "document-upload"],
    queryFn: () => fetchShipments(new URLSearchParams("page_size=100")),
    enabled: open,
  });
  const documents = useQuery({
    queryKey: ["documents", deferredQuery, status, documentTypeFilter],
    queryFn: () =>
      fetchOperationsList("/documents", {
        ...(deferredQuery ? { q: deferredQuery } : {}),
        ...(status ? { status } : {}),
        ...(documentTypeFilter ? { document_type: documentTypeFilter } : {}),
      }),
  });
  const mutation = useMutation({
    mutationFn: () => {
      if (!shipmentId || !file)
        throw new Error("Pilih pengiriman dan file terlebih dahulu.");
      return uploadDocument({
        shipment_id: shipmentId,
        document_type: documentType,
        file,
      });
    },
    onSuccess: () => {
      setOpen(false);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      client.invalidateQueries({ queryKey: ["documents"] });
    },
  });
  const rows = documents.data?.items || [];
  const [selectedExtraction, setSelectedExtraction] = useState<Row | null>(
    null,
  );

  return (
    <CloudflarePageShell className="cf-documents-page">
      <PageHeader
        icon={FileArrowUp}
        title="Dokumen"
        description="Kelola bukti pengiriman di penyimpanan dokumen, termasuk versi, hasil ekstraksi, dan status peninjauan."
        actions={
          <Button icon={Plus} onClick={() => setOpen(true)}>
            Unggah dokumen
          </Button>
        }
      />
      <FilterBar label="Filter dokumen">
        <SearchField
          value={query}
          onChange={setQuery}
          placeholder="Cari nama file atau pengiriman"
          ariaLabel="Cari dokumen"
        />
        <span className="cf-metadata">{rows.length} record</span>
        <AppSelect
          ariaLabel="Filter jenis dokumen"
          value={documentTypeFilter}
          onValueChange={setDocumentTypeFilter}
          options={documentTypes}
        />
        <AppSelect
          ariaLabel="Filter status peninjauan"
          value={status}
          onValueChange={setStatus}
          options={[
            { value: "", label: "Semua status" },
            { value: "PENDING", label: "Menunggu" },
            { value: "REVIEW", label: "Perlu ditinjau" },
            { value: "APPROVED", label: "Disetujui" },
          ]}
        />
      </FilterBar>
      {documents.isPending ? (
        <LoadingState
          label="Memuat penyimpanan dokumen…"
          className="page-loading"
        />
      ) : documents.isError ? (
        <StateNotice
          title="Daftar dokumen tidak tersedia saat ini."
          tone="danger"
        >
          Coba lagi setelah koneksi layanan pulih.
        </StateNotice>
      ) : (
        <DataTableSurface
          title="Daftar dokumen"
          description="Bukti dokumen tetap terkait dengan pengiriman sumbernya; file tidak dapat dibuat hanya melalui metadata."
        >
          {rows.length ? (
            <div className="table-scroll">
              <Table>
                <Table.Header sticky>
                  <Table.Row>
                    <Table.Head>File</Table.Head>
                    <Table.Head>Pengiriman</Table.Head>
                    <Table.Head>Jenis</Table.Head>
                    <Table.Head>Versi</Table.Head>
                    <Table.Head>Ekstraksi</Table.Head>
                    <Table.Head>Confidence</Table.Head>
                    <Table.Head>Review</Table.Head>
                    <Table.Head>Provider</Table.Head>
                    <Table.Head>Diperbarui</Table.Head>
                    <Table.Head>
                      <span className="sr-only">Aksi</span>
                    </Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {rows.map((row) => {
                    const versionData = row.version as Row | undefined;
                    return (
                      <Table.Row key={String(row.id)}>
                        <Table.Cell>
                          <span className="table-cell-primary">
                            {String(row.filename || "—")}
                          </span>
                          <small>{String(row.mime_type || "")}</small>
                        </Table.Cell>
                        <Table.Cell>
                          {String(row.shipment_reference || "—")}
                        </Table.Cell>
                        <Table.Cell>
                          {String(row.document_type || "—")}
                        </Table.Cell>
                        <Table.Cell>{version(row)}</Table.Cell>
                        <Table.Cell>
                          <OperationalState
                            value={String(
                              versionData?.extraction_status || "PENDING",
                            )}
                          />
                        </Table.Cell>
                        <Table.Cell>
                          <span className="mono">{confidence(row)}</span>
                        </Table.Cell>
                        <Table.Cell>
                          <OperationalState
                            value={String(row.status || "PENDING")}
                          />
                        </Table.Cell>
                        <Table.Cell>
                          {String(versionData?.extraction_provider || "—")}
                        </Table.Cell>
                        <Table.Cell>
                          {date(
                            row.extraction_recorded_at ||
                              row.updated_at ||
                              row.created_at,
                          )}
                        </Table.Cell>
                        <Table.Cell>
                          <div className="cf-documents-actions">
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => setSelectedExtraction(row)}
                              disabled={!versionData?.extraction_result_json}
                            >
                              Provenance
                            </Button>
                            <ActionLink
                              href={`/shipments/${String(row.shipment_id)}`}
                              variant="ghost"
                            >
                              Buka
                            </ActionLink>
                          </div>
                        </Table.Cell>
                      </Table.Row>
                    );
                  })}
                </Table.Body>
              </Table>
            </div>
          ) : (
            <EmptyState
              icon={<FileArrowUp size={20} />}
              title="Belum ada dokumen"
              description="Unggah bukti asli untuk memulai ekstraksi dan peninjauan."
              action={
                <Button icon={FileArrowUp} onClick={() => setOpen(true)}>
                  Unggah dokumen
                </Button>
              }
            />
          )}
        </DataTableSurface>
      )}
      {selectedExtraction ? (
        <ExtractionDetail
          row={selectedExtraction}
          onClose={() => setSelectedExtraction(null)}
        />
      ) : null}
      <DialogRoot open={open} onOpenChange={setOpen}>
        <Dialog className="cf-document-upload-dialog">
          <Dialog.Title>Unggah dokumen pengiriman</Dialog.Title>
          <Dialog.Description>
            File asli akan divalidasi sebelum disimpan ke penyimpanan dokumen
            dan dijadwalkan untuk ekstraksi.
          </Dialog.Description>
          <form
            className="dialog-form"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            <label>
              Pengiriman
              <AppSelect
                ariaLabel="Pilih pengiriman"
                value={shipmentId}
                onValueChange={setShipmentId}
                options={[
                  {
                    value: "",
                    label: shipments.isPending
                      ? "Memuat pengiriman…"
                      : "Pilih pengiriman",
                  },
                  ...(shipments.data?.items.map((shipment) => ({
                    value: shipment.id,
                    label: `${shipment.internal_reference} · ${shipment.origin} → ${shipment.destination}`,
                  })) || []),
                ]}
              />
            </label>
            <label>
              Jenis dokumen
              <AppSelect
                ariaLabel="Pilih jenis dokumen"
                value={documentType}
                onValueChange={setDocumentType}
                options={documentTypes.slice(1)}
              />
            </label>
            <div className="cf-file-picker">
              <span>File asli</span>
              <input
                ref={fileInput}
                className="sr-only"
                type="file"
                accept="application/pdf,image/jpeg,image/png"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
              <div>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => fileInput.current?.click()}
                >
                  Pilih file
                </Button>
                <small>
                  {file?.name ||
                    "PDF, JPG, atau PNG sesuai kebijakan ruang kerja"}
                </small>
              </div>
            </div>
            {mutation.isError && (
              <p className="form-error" role="alert">
                {(mutation.error as Error).message}
              </p>
            )}
            <div className="form-panel__actions">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setOpen(false)}
              >
                Batal
              </Button>
              <Button
                type="submit"
                disabled={mutation.isPending || !shipmentId || !file}
              >
                {mutation.isPending ? "Mengunggah…" : "Unggah dokumen"}
              </Button>
            </div>
          </form>
        </Dialog>
      </DialogRoot>
    </CloudflarePageShell>
  );
}
