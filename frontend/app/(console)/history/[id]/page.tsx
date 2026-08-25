"use client";

import { Table } from "@cloudflare/kumo/components/table";
import {
  ArrowLeftIcon as ArrowLeft,
  FileTextIcon as FileText,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { fetchReconciliation } from "@/lib/api";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  operationalStatusLabel,
  operationalTextLabel,
  OperationalState,
  StateNotice,
} from "@/components/ui/operational-primitives";
import {
  CloudflarePageShell,
  DataTableSurface,
  LoadingState,
} from "@/components/ui/page-primitives";
import type { DocumentType } from "@/lib/types";

const labels: Record<DocumentType, string> = {
  delivery_order: "Surat jalan",
  invoice: "Invoice",
  packing_list: "Packing list",
};

export default function HistoryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const result = useQuery({
    queryKey: ["reconciliation", id],
    queryFn: () => fetchReconciliation(id),
  });
  if (result.isPending)
    return (
      <LoadingState label="Memuat pemeriksaan…" className="page-loading" />
    );
  if (result.isError || !result.data)
    return (
      <StateNotice
        title="Pemeriksaan dokumen tidak dapat dimuat."
        tone="danger"
      >
        Coba lagi setelah koneksi layanan pulih.
      </StateNotice>
    );
  const item = result.data;
  return (
    <CloudflarePageShell className="cf-history-detail-page">
      <Link href="/history" className="back-link">
        <ArrowLeft size={15} /> Kembali ke riwayat pemeriksaan
      </Link>
      <PageHeader
        icon={FileText}
        title="Hasil pemeriksaan"
        description={item.reason}
        actions={<StatusBadge status={item.effective_status} />}
      />
      <div className="detail-grid">
        <DataTableSurface
          title="Catatan keputusan"
          description="Keputusan terkini dan langkah berikutnya untuk pengiriman ini."
        >
          <dl className="detail-list">
            <div>
              <dt>Keputusan awal</dt>
              <dd><OperationalState value={item.audit.system_decision} /></dd>
            </div>
            <div>
              <dt>Keputusan akhir</dt>
              <dd><OperationalState value={item.effective_status} /></dd>
            </div>
            <div>
              <dt>Langkah berikutnya</dt>
              <dd>{operationalTextLabel(item.recommended_action)}</dd>
            </div>
            <div>
              <dt>Selesai</dt>
              <dd>{new Date(item.created_at).toLocaleString("id-ID")}</dd>
            </div>
          </dl>
        </DataTableSurface>
        <DataTableSurface
          title="Temuan"
          description="Perbedaan yang memengaruhi keputusan pemeriksaan."
        >
          {item.mismatches.length === 0 ? (
            <p className="empty-copy">Tidak ada perbedaan material.</p>
          ) : (
            <div className="space-y-4">
              {item.mismatches.map((mismatch) => (
                <article key={mismatch.id}>
                  <div className="flex items-center justify-between gap-3">
                    <span className="table-cell-primary">
                      {operationalTextLabel(mismatch.type)}
                    </span>
                    <OperationalState value={mismatch.severity} />
                  </div>
                  <p className="mt-1 text-sm text-[var(--text-subtle)]">
                    {mismatch.explanation}
                  </p>
                </article>
              ))}
            </div>
          )}
        </DataTableSurface>
      </div>
      <DataTableSurface
        title="Detail dokumen"
        description="Informasi yang dibaca dari setiap dokumen yang diunggah."
      >
        <div className="table-scroll">
          <Table>
            <Table.Header sticky>
              <Table.Row>
                <Table.Head>Dokumen</Table.Head>
                <Table.Head>Referensi dokumen</Table.Head>
                <Table.Head>Referensi pengiriman</Table.Head>
                <Table.Head>Penerima</Table.Head>
                <Table.Head>Keterbacaan</Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {(
                Object.entries(item.documents) as [
                  DocumentType,
                  (typeof item.documents)[DocumentType],
                ][]
              ).map(([type, doc]) => (
                <Table.Row key={type}>
                  <Table.Cell>{labels[type]}</Table.Cell>
                  <Table.Cell>
                    {String(doc.document_id.value || "Tidak tersedia")}
                  </Table.Cell>
                  <Table.Cell>
                    {String(doc.shipment_id.value || "Tidak tersedia")}
                  </Table.Cell>
                  <Table.Cell>
                    {String(doc.recipient.value || "Tidak tersedia")}
                  </Table.Cell>
                  <Table.Cell>
                    {Math.round(doc.document_type_confidence * 100)}%
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        </div>
      </DataTableSurface>
      {item.audit.override_history.length > 0 && (
        <DataTableSurface
          title="Perubahan keputusan"
          description="Perubahan supervisor dan alasannya yang tersimpan."
        >
          <div className="space-y-3">
            {item.audit.override_history.map((event) => (
              <div
                key={event.id}
                className="border-l-2 border-blue-500 pl-4 text-sm"
              >
                <strong>
                  {operationalStatusLabel(event.previous_decision)} → {operationalStatusLabel(event.final_decision)}
                </strong>
                <p className="mt-1 text-[var(--text-subtle)]">{event.reason}</p>
                <small className="text-[var(--text-subtle)]">
                  {event.actor} ·{" "}
                  {new Date(event.created_at).toLocaleString("id-ID")}
                </small>
              </div>
            ))}
          </div>
        </DataTableSurface>
      )}
    </CloudflarePageShell>
  );
}
