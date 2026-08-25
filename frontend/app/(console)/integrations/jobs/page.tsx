"use client";

import { Table } from "@cloudflare/kumo/components/table";
import {
  ArrowsClockwiseIcon as Retry,
  ListChecksIcon as Jobs,
  PulseIcon as Pulse,
} from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ActionLink, Button } from "@/components/ui/button";
import {
  DataTableSurface,
  EmptyState,
  FilterBar,
  LoadingState,
  SearchField,
} from "@/components/ui/page-primitives";
import {
  operationalStatusLabel,
  operationalTextLabel,
  OperationalState,
  StateNotice,
} from "@/components/ui/operational-primitives";
import { PageHeader } from "@/components/ui/page-header";
import { AppSelect } from "@/components/ui/select";
import { fetchOperationsList, retryJob } from "@/lib/api";

type Job = {
  id: string;
  job_type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  priority: number;
  queued_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  error_code?: string | null;
  safe_error?: string | null;
  shipment_id?: string | null;
};
const date = (value?: string | null) =>
  value
    ? new Intl.DateTimeFormat("id-ID", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "—";

export default function JobsPage() {
  const client = useQueryClient();
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const result = useQuery({
    queryKey: ["integration-jobs"],
    queryFn: () => fetchOperationsList("/integrations/jobs"),
  });
  const retry = useMutation({
    mutationFn: retryJob,
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["integration-jobs"] }),
  });
  const jobs = useMemo(
    () => (result.data?.items || []) as Job[],
    [result.data],
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return jobs.filter(
      (job) =>
        (!status || job.status === status) &&
        (!needle ||
          [
            job.id,
            job.job_type,
            job.shipment_id,
            job.error_code,
            job.safe_error,
          ].some((value) => value?.toLowerCase().includes(needle))),
    );
  }, [jobs, query, status]);

  return (
    <div className="operations-page cf-integration-jobs-page">
      <PageHeader
        icon={Jobs}
        title="Proses latar belakang"
        description="Daftar proses ekstraksi, penilaian, dan pengiriman yang tersimpan di ruang kerja."
        actions={
          <ActionLink href="/observability" variant="secondary" icon={Pulse}>
            Buka pemantauan
          </ActionLink>
        }
      />
      <StateNotice title="Cakupan daftar proses" tone="info">
        Data berasal dari API; payload dan kredensial disembunyikan.
      </StateNotice>
      <FilterBar
        className="cf-job-toolbar"
        label="Filter proses latar belakang"
      >
        <SearchField
          value={query}
          onChange={setQuery}
          placeholder="Cari ID, jenis, pengiriman, atau error"
          ariaLabel="Cari proses"
        />
        <AppSelect
          ariaLabel="Filter status proses"
          value={status}
          onValueChange={setStatus}
          options={[
            { value: "", label: "Semua status" },
            ...["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "DEAD_LETTER"].map(
              (value) => ({ value, label: operationalStatusLabel(value) }),
            ),
          ]}
        />
      </FilterBar>
      <DataTableSurface
        title="Daftar proses"
        description={`${filtered.length} dari ${jobs.length} proses pada respons ini. Pesan kesalahan hanya ditampilkan bila backend mencatat versi aman.`}
      >
        {result.isLoading ? (
          <LoadingState label="Memuat proses…" />
        ) : result.error ? (
          <EmptyState
            icon={<Jobs size={18} />}
            title="Daftar proses belum dapat dimuat"
            description={
              result.error instanceof Error
                ? result.error.message
                : "Muat ulang saat API tersedia."
            }
          />
        ) : !filtered.length ? (
          <EmptyState
            icon={<Jobs size={18} />}
            title="Tidak ada proses yang cocok"
            description="Ubah kata kunci atau status untuk melihat proses lain."
          />
        ) : (
          <div className="table-scroll">
            <Table>
              <Table.Header sticky>
                <Table.Row>
                  <Table.Head>Antrean</Table.Head>
                  <Table.Head>Jenis</Table.Head>
                  <Table.Head>Status</Table.Head>
                  <Table.Head>Upaya</Table.Head>
                  <Table.Head>Prioritas</Table.Head>
                  <Table.Head>Pengiriman</Table.Head>
                  <Table.Head>Pesan aman</Table.Head>
                  <Table.Head>
                    <span className="sr-only">Aksi</span>
                  </Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {filtered.map((job) => (
                  <Table.Row key={job.id}>
                    <Table.Cell>
                      <span className="cf-table-date">
                        {date(job.queued_at)}
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="table-cell-primary">{operationalTextLabel(job.job_type)}</span>
                      <br />
                      <span className="cf-metadata mono">
                        {job.id.slice(0, 8)}
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      <OperationalState value={job.status} />
                    </Table.Cell>
                    <Table.Cell>
                      <span className="mono">
                        {job.attempts}/{job.max_attempts}
                      </span>
                    </Table.Cell>
                    <Table.Cell>{job.priority}</Table.Cell>
                    <Table.Cell>
                      <span className="mono">
                        {job.shipment_id?.slice(0, 8) || "—"}
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="cf-safe-error">
                        {job.safe_error || "—"}
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      {["FAILED", "DEAD_LETTER"].includes(job.status) ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          icon={Retry}
                          disabled={retry.isPending}
                          onClick={() => retry.mutate(job.id)}
                        >
                          {retry.isPending ? "Mengantrekan…" : "Coba lagi"}
                        </Button>
                      ) : (
                        <span className="cf-metadata">—</span>
                      )}
                    </Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </div>
        )}
        {retry.isError && (
          <p className="form-error" role="alert">
            {(retry.error as Error).message}
          </p>
        )}
      </DataTableSurface>
    </div>
  );
}
