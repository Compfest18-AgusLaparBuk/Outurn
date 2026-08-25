"use client";

import { Table } from "@cloudflare/kumo/components/table";
import { ClockCounterClockwiseIcon as ClockCounterClockwise } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";
import { PageHeader } from "@/components/ui/page-header";
import { AppSelect } from "@/components/ui/select";
import {
  AppPagination,
  DataTableSurface,
  FilterBar,
  LoadingState,
  SearchField,
} from "@/components/ui/page-primitives";
import { StatusBadge } from "@/components/ui/status-badge";
import { StateNotice } from "@/components/ui/operational-primitives";
import { fetchHistory } from "@/lib/api";

export default function HistoryPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const params = useMemo(() => {
    const value = new URLSearchParams({ page: String(page), page_size: "20" });
    if (status) value.set("status", status);
    if (deferredQuery) value.set("query", deferredQuery);
    return value;
  }, [deferredQuery, page, status]);
  const result = useQuery({
    queryKey: ["history", params.toString()],
    queryFn: () => fetchHistory(params),
  });

  return (
    <div>
      <PageHeader
        icon={ClockCounterClockwise}
        title="Riwayat pemeriksaan"
        description="Cari pemeriksaan dokumen sebelumnya dan tinjau evidence tanpa mengunggah file kembali."
      />
      <FilterBar label="Filter riwayat pemeriksaan">
        <SearchField
          value={query}
          onChange={(value) => {
            setPage(1);
            setQuery(value);
          }}
          placeholder="Cari referensi pengiriman atau dokumen"
          ariaLabel="Cari pengiriman atau dokumen"
        />
        <AppSelect
          ariaLabel="Filter status"
          value={status}
          onValueChange={(nextStatus) => {
            setPage(1);
            setStatus(nextStatus);
          }}
          options={[
            { value: "", label: "Semua keputusan" },
            { value: "CLEAR", label: "Siap dilepas" },
            { value: "REVIEW", label: "Perlu tinjauan" },
            { value: "HOLD", label: "Ditahan" },
          ]}
        />
      </FilterBar>
      {result.isError && (
        <StateNotice
          title="Riwayat pemeriksaan belum dapat dimuat."
          tone="danger"
        >
          Coba lagi setelah koneksi layanan pulih.
        </StateNotice>
      )}
      <DataTableSurface className="data-panel--wide">
        {result.isPending ? (
          <LoadingState
            label="Memuat riwayat pemeriksaan…"
            className="page-loading"
          />
        ) : (
          <div className="table-scroll">
            <Table>
              <Table.Header sticky>
                <Table.Row>
                  <Table.Head>Waktu</Table.Head>
                  <Table.Head>Pengiriman / dokumen</Table.Head>
                  <Table.Head>Keputusan sistem</Table.Head>
                  <Table.Head>Keputusan akhir</Table.Head>
                  <Table.Head>Temuan</Table.Head>
                  <Table.Head>Pemrosesan</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {result.data?.items.map((item) => (
                  <Table.Row key={item.session_id}>
                    <Table.Cell>
                      {new Date(item.created_at).toLocaleString("id-ID")}
                    </Table.Cell>
                    <Table.Cell>
                      <Link
                        className="table-link"
                        href={`/history/${item.session_id}`}
                      >
                        {String(
                          item.documents.delivery_order?.shipment_id.value ||
                            item.session_id.slice(0, 8),
                        )}
                      </Link>
                      <small>
                        {String(
                          item.documents.delivery_order?.document_id.value ||
                            "Tidak ada referensi dokumen",
                        )}
                      </small>
                    </Table.Cell>
                    <Table.Cell>
                      <StatusBadge status={item.status} />
                    </Table.Cell>
                    <Table.Cell>
                      <StatusBadge status={item.effective_status} />
                    </Table.Cell>
                    <Table.Cell>{item.mismatches.length}</Table.Cell>
                    <Table.Cell>{item.processing_ms} ms</Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </div>
        )}
      </DataTableSurface>
      {result.data && (
        <AppPagination
          page={page}
          perPage={result.data.page_size}
          totalCount={result.data.total}
          setPage={setPage}
        />
      )}
    </div>
  );
}
