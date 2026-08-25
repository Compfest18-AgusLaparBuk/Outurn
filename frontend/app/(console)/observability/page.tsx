"use client";

import {
  ActivityIcon as Activity,
  ArrowsClockwiseIcon as Refresh,
  ClockCounterClockwiseIcon as History,
  QueueIcon as Queue,
} from "@phosphor-icons/react";
import { Dialog } from "@cloudflare/kumo/components/dialog";
import { Table } from "@cloudflare/kumo/components/table";
import { Tabs } from "@cloudflare/kumo/components/tabs";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  DataTableSurface,
  EmptyState,
  FilterBar,
  LoadingState,
  SearchField,
} from "@/components/ui/page-primitives";
import {
  MetricCell,
  operationalStatusLabel,
  OperationalState,
  StateNotice,
} from "@/components/ui/operational-primitives";
import { PageHeader } from "@/components/ui/page-header";
import { AppSelect } from "@/components/ui/select";
import { fetchObservability } from "@/lib/api";

type Tab = "overview" | "jobs" | "workers";
type ProcessingJob = {
  id: string;
  job_type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  priority: number;
  queued_at: string;
  started_at?: string | null;
  heartbeat_at?: string | null;
  completed_at?: string | null;
  error_code?: string | null;
  safe_error?: string | null;
  shipment_id?: string | null;
};
type Worker = {
  worker_id: string;
  status: string;
  version?: string | null;
  last_heartbeat_at: string;
  current_job_id?: string | null;
};
type ObservabilityData = {
  application?: string;
  database?: string;
  worker?: string;
  extraction?: string;
  webhook?: string;
  workers?: Worker[];
  jobs?: ProcessingJob[];
  queue_depth?: number;
  jobs_succeeded?: number;
  jobs_failed?: number;
  oldest_queued_job?: ProcessingJob | null;
  connections?: { total?: number; enabled?: number };
};

const tabs = [
  { value: "overview", label: "Ringkasan" },
  { value: "jobs", label: "Proses latar belakang" },
  { value: "workers", label: "Worker" },
];
const jobStatusOptions = [
  { value: "all", label: "Semua status" },
  ...["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "DEAD_LETTER"].map(
    (value) => ({ value, label: operationalStatusLabel(value) }),
  ),
];
const dateTime = (value?: string | null) =>
  value
    ? new Intl.DateTimeFormat("id-ID", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "—";

function JobDetailDialog({
  job,
  onClose,
}: {
  job: ProcessingJob;
  onClose: () => void;
}) {
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog className="cf-job-detail-dialog" size="base">
        <Dialog.Title>Detail proses</Dialog.Title>
        <Dialog.Description>
          Informasi operasional aman dari proses tersimpan. Muatan dan
          kredensial tidak ditampilkan.
        </Dialog.Description>
        <dl className="cf-job-detail-grid">
          <div>
            <dt>ID job</dt>
            <dd className="mono">{job.id}</dd>
          </div>
          <div>
            <dt>Jenis</dt>
            <dd>{job.job_type}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <OperationalState value={job.status} />
            </dd>
          </div>
          <div>
            <dt>Prioritas</dt>
            <dd>{job.priority}</dd>
          </div>
          <div>
            <dt>Antrean</dt>
            <dd>{dateTime(job.queued_at)}</dd>
          </div>
          <div>
            <dt>Mulai</dt>
            <dd>{dateTime(job.started_at)}</dd>
          </div>
          <div>
            <dt>Selesai</dt>
            <dd>{dateTime(job.completed_at)}</dd>
          </div>
          <div>
            <dt>Upaya</dt>
            <dd>
              {job.attempts} / {job.max_attempts}
            </dd>
          </div>
          <div>
            <dt>Shipment</dt>
            <dd className="mono">{job.shipment_id || "—"}</dd>
          </div>
          <div>
            <dt>Kode error</dt>
            <dd className="mono">{job.error_code || "—"}</dd>
          </div>
        </dl>
        {job.safe_error ? (
          <StateNotice title="Pesan aman" tone="danger">
            {job.safe_error}
          </StateNotice>
        ) : (
          <StateNotice title="Tidak ada pesan aman" tone="info">
            Proses ini belum merekam kesalahan yang aman untuk ditampilkan.
          </StateNotice>
        )}
        <div className="form-panel__actions">
          <Button variant="secondary" onClick={onClose}>
            Tutup
          </Button>
        </div>
      </Dialog>
    </Dialog.Root>
  );
}

export default function ObservabilityPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [selectedJob, setSelectedJob] = useState<ProcessingJob | null>(null);
  const result = useQuery({
    queryKey: ["observability"],
    queryFn: fetchObservability,
    refetchInterval: 30_000,
  });
  const data = (result.data || {}) as ObservabilityData;
  const health = [
    ["Aplikasi", data.application],
    ["Basis data", data.database],
    ["Worker", data.worker],
    ["Ekstraksi", data.extraction],
    ["Webhook", data.webhook],
  ];
  const jobs = useMemo(() => data.jobs || [], [data.jobs]);
  const filteredJobs = useMemo(
    () =>
      jobs.filter((job) => {
        const matchesStatus = status === "all" || job.status === status;
        const needle = query.trim().toLowerCase();
        return (
          matchesStatus &&
          (!needle ||
            [
              job.id,
              job.job_type,
              job.status,
              job.error_code,
              job.shipment_id,
            ].some((value) => value?.toLowerCase().includes(needle)))
        );
      }),
    [jobs, query, status],
  );
  const refresh = () => {
    void result.refetch();
  };

  return (
    <div className="operations-page cf-observability-page">
      <PageHeader
        icon={Activity}
        title="Observability"
        description="Ketersediaan layanan dan proses latar belakang untuk workspace ini. Data diperbarui otomatis setiap 30 detik."
        actions={
          <Button
            size="sm"
            variant="secondary"
            icon={Refresh}
            onClick={refresh}
            disabled={result.isFetching}
          >
            {result.isFetching ? "Memuat…" : "Muat ulang"}
          </Button>
        }
      />
      {result.error ? (
        <StateNotice title="Observability tidak dapat dimuat" tone="danger">
          {result.error instanceof Error
            ? result.error.message
            : "Coba muat ulang data operasional."}
        </StateNotice>
      ) : null}
      <Tabs
        tabs={tabs}
        value={tab}
        onValueChange={(value) => setTab(value as Tab)}
        className="detail-tabs"
        aria-label="Bagian Observability"
      />

      {tab === "overview" && (
        <div className="cf-observability-stack">
          <section
            className="health-strip cf-health-strip"
            aria-label="Kesehatan layanan"
          >
            {health.map(([label, state]) => (
              <div className="health-cell" key={String(label)}>
                <span>{String(label)}</span>
                <OperationalState value={String(state || "unknown")} />
              </div>
            ))}
          </section>
          {data.webhook === "configured_queued" ? (
            <StateNotice title="Webhook terkonfigurasi" tone="info">
              Event masuk antrean worker dan ditandatangani HMAC.
            </StateNotice>
          ) : null}
          <section
            className="metric-grid metric-grid--four"
            aria-label="Ringkasan pemrosesan"
          >
            <MetricCell
              label="Antrean aktif"
              value={result.isLoading ? "—" : String(data.queue_depth ?? 0)}
              detail="Menunggu atau sedang berjalan"
            />
            <MetricCell
              label="Berhasil"
              value={result.isLoading ? "—" : String(data.jobs_succeeded ?? 0)}
              detail="Dari proses yang dikembalikan"
            />
            <MetricCell
              label="Gagal"
              value={result.isLoading ? "—" : String(data.jobs_failed ?? 0)}
              detail="Gagal atau gagal permanen"
            />
            <MetricCell
              label="Koneksi aktif"
              value={
                result.isLoading ? "—" : String(data.connections?.enabled ?? 0)
              }
              detail={`${data.connections?.total ?? 0} koneksi terdaftar`}
            />
          </section>
          <div className="cf-observability-overview-grid">
            <section className="data-panel">
              <div className="data-panel__header">
                <div>
                  <h2>Antrean pemrosesan</h2>
                  <p>
                    Proses disimpan agar kegagalan dapat diselidiki dengan aman.
                  </p>
                </div>
                <Queue size={20} />
              </div>
              {data.oldest_queued_job ? (
                <div className="cf-queue-detail">
                  <span className="cf-label">Proses tertua di antrean</span>
                  <span>{data.oldest_queued_job.job_type}</span>
                  <span className="cf-metadata">
                    Sejak {dateTime(data.oldest_queued_job.queued_at)}
                  </span>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setSelectedJob(data.oldest_queued_job || null);
                      setTab("jobs");
                    }}
                  >
                    Lihat proses
                  </Button>
                </div>
              ) : (
                <EmptyState
                  icon={<Queue size={18} />}
                  title="Antrean kosong"
                  description="Tidak ada proses yang sedang menunggu pada respons operasional saat ini."
                />
              )}
            </section>
            <section className="data-panel">
              <div className="data-panel__header">
                <div>
                  <h2>Peristiwa pemrosesan terbaru</h2>
                  <p>Daftar proses tersimpan, bukan stream log buatan.</p>
                </div>
                <History size={20} />
              </div>
              {jobs.length ? (
                <ul className="cf-job-event-list">
                  {jobs.slice(0, 5).map((job) => (
                    <li key={job.id}>
                      <div>
                        <span>{job.job_type}</span>
                        <small>
                          {dateTime(
                            job.completed_at || job.started_at || job.queued_at,
                          )}
                        </small>
                      </div>
                      <OperationalState value={job.status} />
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  icon={<History size={18} />}
                  title="Belum ada proses latar belakang"
                  description="Proses akan muncul di sini setelah dokumen atau pekerjaan operasional masuk ke antrean."
                />
              )}
            </section>
          </div>
          <StateNotice title="Cakupan data" tone="info">
            Hanya kesehatan layanan dan proses tersimpan yang ditampilkan.
          </StateNotice>
        </div>
      )}

      {tab === "jobs" && (
        <section className="cf-observability-stack">
          <FilterBar
            className="cf-job-toolbar"
            label="Filter proses latar belakang"
          >
            <SearchField
              value={query}
              onChange={setQuery}
              placeholder="Cari ID, jenis, shipment, atau kesalahan"
              ariaLabel="Cari proses"
            />
            <AppSelect
              ariaLabel="Filter status proses"
              value={status}
              onValueChange={setStatus}
              options={jobStatusOptions}
            />
          </FilterBar>
          <DataTableSurface
            title="Proses latar belakang"
            description="Maksimal 20 proses terbaru dari API. Pilih Detail untuk melihat waktunya dan pesan aman."
          >
            {result.isLoading ? (
              <LoadingState label="Memuat proses…" />
            ) : !filteredJobs.length ? (
              <EmptyState
                icon={<History size={18} />}
                title="Tidak ada proses yang cocok"
                description={
                  jobs.length
                    ? "Ubah filter status atau kata kunci untuk melihat proses lain."
                    : "Belum ada proses tersimpan untuk workspace ini."
                }
              />
            ) : (
              <div className="table-scroll">
                <Table>
                  <Table.Header sticky>
                    <Table.Row>
                      <Table.Head>Waktu antrean</Table.Head>
                      <Table.Head>Jenis</Table.Head>
                      <Table.Head>Status</Table.Head>
                      <Table.Head>Upaya</Table.Head>
                      <Table.Head>Pesan aman</Table.Head>
                      <Table.Head aria-label="Aksi" />
                    </Table.Row>
                  </Table.Header>
                  <Table.Body>
                    {filteredJobs.map((job) => (
                      <Table.Row key={job.id}>
                        <Table.Cell>
                          <span className="cf-table-date">
                            {dateTime(job.queued_at)}
                          </span>
                        </Table.Cell>
                        <Table.Cell>
                          <span className="table-cell-primary">
                            {job.job_type}
                          </span>
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
                        <Table.Cell>
                          <span className="cf-safe-error">
                            {job.safe_error || "—"}
                          </span>
                        </Table.Cell>
                        <Table.Cell>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => setSelectedJob(job)}
                          >
                            Detail
                          </Button>
                        </Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table>
              </div>
            )}
          </DataTableSurface>
        </section>
      )}

      {tab === "workers" && (
        <section className="cf-observability-stack">
          <StateNotice title="Worker aktif" tone="info">
            Hanya worker dengan heartbeat dua menit terakhir yang ditampilkan.
          </StateNotice>
          <DataTableSurface
            title="Workers aktif"
            description="Heartbeat terbaru dari worker yang live pada respons ini."
          >
            {result.isLoading ? (
              <LoadingState label="Memuat heartbeat worker…" />
            ) : !(data.workers || []).length ? (
              <EmptyState
                icon={<Activity size={18} />}
                title="Tidak ada worker live"
                description="Periksa deployment worker jika pemrosesan diperlukan. Status ini bukan bukti bahwa tidak ada worker terdaftar."
              />
            ) : (
              <div className="table-scroll">
                <Table>
                  <Table.Header sticky>
                    <Table.Row>
                      <Table.Head>Worker</Table.Head>
                      <Table.Head>Status</Table.Head>
                      <Table.Head>Versi</Table.Head>
                      <Table.Head>Heartbeat terakhir</Table.Head>
                      <Table.Head>Job saat ini</Table.Head>
                    </Table.Row>
                  </Table.Header>
                  <Table.Body>
                    {(data.workers || []).map((worker) => (
                      <Table.Row key={worker.worker_id}>
                        <Table.Cell>
                          <span className="table-cell-primary mono">
                            {worker.worker_id}
                          </span>
                        </Table.Cell>
                        <Table.Cell>
                          <OperationalState value={worker.status} />
                        </Table.Cell>
                        <Table.Cell>{worker.version || "—"}</Table.Cell>
                        <Table.Cell>
                          {dateTime(worker.last_heartbeat_at)}
                        </Table.Cell>
                        <Table.Cell>
                          <span className="mono">
                            {worker.current_job_id || "—"}
                          </span>
                        </Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table>
              </div>
            )}
          </DataTableSurface>
        </section>
      )}
      {selectedJob ? (
        <JobDetailDialog
          job={selectedJob}
          onClose={() => setSelectedJob(null)}
        />
      ) : null}
    </div>
  );
}
