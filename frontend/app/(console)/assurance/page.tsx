"use client";

import { Table } from "@cloudflare/kumo/components/table";
import { ShieldCheckIcon as ShieldCheck } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ActionLink } from "@/components/ui/button";
import {
  operationalStatusLabel,
  operationalTextLabel,
  OperationalState,
  StateNotice,
} from "@/components/ui/operational-primitives";
import { PageHeader } from "@/components/ui/page-header";
import {
  CloudflarePageShell,
  DataTableSurface,
  EmptyState,
  LoadingState,
  FilterBar,
} from "@/components/ui/page-primitives";
import { AppSelect } from "@/components/ui/select";
import { fetchOperationsList } from "@/lib/api";

type Row = Record<string, unknown>;
function details(value: unknown) {
  return (value && typeof value === "object" ? value : {}) as Row;
}
function date(value: unknown) {
  return value ? new Date(String(value)).toLocaleString("id-ID") : "—";
}

export default function AssurancePage() {
  const [status, setStatus] = useState("");
  const [checkType, setCheckType] = useState("");
  const result = useQuery({
    queryKey: ["assurance", status, checkType],
    queryFn: () =>
      fetchOperationsList("/assurance", {
        ...(status ? { status } : {}),
        ...(checkType ? { check_type: checkType } : {}),
      }),
  });
  const rows = result.data?.items || [];
  return (
    <CloudflarePageShell className="cf-assurance-page">
      <PageHeader
        icon={ShieldCheck}
        title="Pemeriksaan jaminan"
        description="Tinjau pemeriksaan yang mendukung atau menahan keputusan pelepasan berdasarkan sumber dan bukti yang tersimpan."
      />
      <FilterBar label="Filter pemeriksaan jaminan">
        <AppSelect
          ariaLabel="Filter status pemeriksaan"
          value={status}
          onValueChange={setStatus}
          options={[
            { value: "", label: "Semua status" },
            ...["CLEAR", "REVIEW", "HOLD", "FAILED"].map((value) => ({
              value,
              label: operationalStatusLabel(value),
            })),
          ]}
        />
        <AppSelect
          ariaLabel="Filter jenis pemeriksaan"
          value={checkType}
          onValueChange={setCheckType}
          options={[
            { value: "", label: "Semua pemeriksaan" },
            { value: "PARTY_SCREENING", label: "Penyaringan pihak" },
            { value: "DOCUMENT", label: "Dokumen" },
            { value: "DANGEROUS_GOODS", label: "Barang berbahaya" },
          ]}
        />
        <span className="cf-metadata">{rows.length} pemeriksaan</span>
      </FilterBar>
      {result.isPending ? (
        <LoadingState
          label="Memuat pemeriksaan jaminan…"
          className="page-loading"
        />
      ) : result.isError ? (
        <StateNotice
          title="Pemeriksaan jaminan tidak tersedia saat ini."
          tone="danger"
        >
          Coba lagi setelah koneksi layanan pulih.
        </StateNotice>
      ) : (
        <DataTableSurface
          title="Pemeriksaan kepatuhan"
          description="Setiap hasil memiliki arti operasional berbeda; warna tidak menggantikan teks status."
        >
          {rows.length ? (
            <div className="table-scroll">
              <Table>
                <Table.Header sticky>
                  <Table.Row>
                    <Table.Head>Pemeriksaan</Table.Head>
                    <Table.Head>Kategori</Table.Head>
                    <Table.Head>Pengiriman</Table.Head>
                    <Table.Head>Status</Table.Head>
                    <Table.Head>Tingkat risiko</Table.Head>
                    <Table.Head>Bukti</Table.Head>
                    <Table.Head>Sumber</Table.Head>
                    <Table.Head>Dievaluasi</Table.Head>
                    <Table.Head>Relevansi keputusan</Table.Head>
                    <Table.Head>
                      <span className="sr-only">Aksi</span>
                    </Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {rows.map((row) => {
                    const detail = details(row.details);
                    const evidence =
                      detail.evidence ?? detail.evidence_count ?? "—";
                    const relevance =
                      detail.decision_relevance ??
                      detail.release_relevance ??
                      "—";
                    return (
                      <Table.Row key={String(row.id)}>
                        <Table.Cell>
                          <span className="table-cell-primary">
                            {operationalTextLabel(
                              String(row.check_type || "—"),
                            )}
                          </span>
                        </Table.Cell>
                        <Table.Cell>
                          {operationalTextLabel(String(detail.category || "—"))}
                        </Table.Cell>
                        <Table.Cell>
                          {String(row.shipment_reference || "—")}
                        </Table.Cell>
                        <Table.Cell>
                          <OperationalState
                            value={String(row.status || "REVIEW")}
                          />
                        </Table.Cell>
                        <Table.Cell>
                          <OperationalState
                            value={String(row.severity || "—")}
                          />
                        </Table.Cell>
                        <Table.Cell>
                          {typeof evidence === "string" ||
                          typeof evidence === "number"
                            ? String(evidence)
                            : "Tersedia"}
                        </Table.Cell>
                        <Table.Cell>
                          {operationalTextLabel(String(row.source || "—"))}
                        </Table.Cell>
                        <Table.Cell>{date(row.completed_at)}</Table.Cell>
                        <Table.Cell>
                          {typeof relevance === "string"
                            ? operationalTextLabel(relevance)
                            : "Tersedia"}
                        </Table.Cell>
                        <Table.Cell>
                          {row.shipment_id ? (
                            <ActionLink
                              href={`/shipments/${String(row.shipment_id)}`}
                              variant="ghost"
                            >
                              Buka
                            </ActionLink>
                          ) : (
                            <span className="cf-metadata">—</span>
                          )}
                        </Table.Cell>
                      </Table.Row>
                    );
                  })}
                </Table.Body>
              </Table>
            </div>
          ) : (
            <EmptyState
              icon={<ShieldCheck size={20} />}
              title="Belum ada pemeriksaan"
              description="Pemeriksaan akan muncul setelah penilaian atau penyaringan dijalankan."
            />
          )}
        </DataTableSurface>
      )}
    </CloudflarePageShell>
  );
}
