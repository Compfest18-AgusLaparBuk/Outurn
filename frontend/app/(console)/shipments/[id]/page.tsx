"use client";

import {
  ArrowLeftIcon as ArrowLeft,
  PackageIcon as Package,
  ShieldCheckIcon as ShieldCheck,
} from "@phosphor-icons/react";
import { Table } from "@cloudflare/kumo/components/table";
import { Tabs } from "@cloudflare/kumo/components/tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  ContextRail,
  KeyValueList,
  operationalStatusLabel,
  OperationalState,
  RailSection,
  StateNotice,
} from "@/components/ui/operational-primitives";
import { PageHeader } from "@/components/ui/page-header";
import {
  CloudflarePageShell,
  DataTableSurface,
  EmptyState,
  LoadingState,
} from "@/components/ui/page-primitives";
import { AppTextarea } from "@/components/ui/textarea";
import {
  assessShipment,
  decideRelease,
  fetchReleaseGate,
  fetchTrustedReference,
  fetchWorkspaceContext,
  fetchWorkspaceShipment,
  transitionShipment,
} from "@/lib/api";

const labels: Record<string, string> = {
  DRAFT: "Draf",
  DOCUMENTS_REQUIRED: "Dokumen diperlukan",
  REVIEW_REQUIRED: "Perlu ditinjau",
  HOLD: "Ditahan",
  RELEASE_PENDING_APPROVAL: "Menunggu persetujuan kedua",
  RELEASE_AUTHORIZED: "Siap dirilis",
  RELEASE_INVALIDATED: "Pelepasan dibatalkan",
  DISPATCHED: "Dikirim",
  CLOSED: "Ditutup",
};
const tabs = [
  "Ringkasan",
  "Dokumen",
  "Barang",
  "Pihak",
  "Transport",
  "Jaminan",
  "Pengecualian",
  "Timeline",
] as const;
type Tab = (typeof tabs)[number];
type Row = Record<string, unknown>;

function value(row: Row | undefined, key: string, fallback = "Belum tersedia") {
  const result = row?.[key];
  return result === null || result === undefined || result === ""
    ? fallback
    : String(result);
}
function date(value: unknown) {
  return value
    ? new Date(String(value)).toLocaleString("id-ID")
    : "Belum tersedia";
}
function localStatus(status: string) {
  return labels[status] || operationalStatusLabel(status);
}

export default function ShipmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("Ringkasan");
  const [reason, setReason] = useState("");
  const workspace = useQuery({
    queryKey: ["shipment-workspace", id],
    queryFn: () => fetchWorkspaceShipment(id),
  });
  const gateSnapshot = useQuery({
    queryKey: ["shipment-release-gate", id],
    queryFn: () => fetchReleaseGate(id),
  });
  const trustedReference = useQuery({
    queryKey: ["shipment-trusted-reference", id],
    queryFn: () => fetchTrustedReference(id),
    retry: false,
  });
  const context = useQuery({
    queryKey: ["workspace-context"],
    queryFn: fetchWorkspaceContext,
  });
  const assessment = useMutation({
    mutationFn: () => assessShipment(id),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["shipment-workspace", id] });
      client.invalidateQueries({ queryKey: ["shipment-release-gate", id] });
    },
  });
  const decision = useMutation({
    mutationFn: (decisionValue: "AUTHORIZE" | "HOLD") =>
      decideRelease(id, { decision: decisionValue, reason }),
    onSuccess: () => {
      setReason("");
      client.invalidateQueries({ queryKey: ["shipment-workspace", id] });
      client.invalidateQueries({ queryKey: ["work-queue"] });
    },
  });
  const move = useMutation({
    mutationFn: (status: string) => transitionShipment(id, status),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["shipment-workspace", id] }),
  });

  if (workspace.isPending)
    return (
      <CloudflarePageShell>
        <LoadingState
          label="Memuat detail pengiriman…"
          className="page-loading"
        />
      </CloudflarePageShell>
    );
  if (workspace.isError || !workspace.data)
    return (
      <CloudflarePageShell>
        <StateNotice
          title="Detail pengiriman tidak dapat dimuat."
          tone="danger"
        >
          Coba lagi setelah koneksi layanan pulih.
        </StateNotice>
      </CloudflarePageShell>
    );

  const data = workspace.data as Row;
  const shipment = data.shipment as Row;
  const status = value(shipment, "status", "DRAFT");
  const canDecide =
    context.data?.role === "admin" || context.data?.role === "supervisor";
  const list = (key: string) =>
    Array.isArray(data[key]) ? (data[key] as Row[]) : [];
  const gate = Array.isArray(gateSnapshot.data?.gate)
    ? (gateSnapshot.data.gate as Row[])
    : list("release_gate");
  const blockers = Array.isArray(gateSnapshot.data?.blockers)
    ? (gateSnapshot.data.blockers as Row[])
    : [];
  const rows = (items: Row[], columns: Array<[string, string]>) =>
    items.length ? (
      <div className="table-scroll">
        <Table>
          <Table.Header sticky>
            <Table.Row>
              {columns.map(([key, heading]) => (
                <Table.Head key={key}>{heading}</Table.Head>
              ))}
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {items.map((row, index) => (
              <Table.Row key={String(row.id || index)}>
                {columns.map(([key]) => (
                  <Table.Cell key={key}>
                    {key === "created_at" || key.endsWith("_at")
                      ? date(row[key])
                      : value(row, key)}
                  </Table.Cell>
                ))}
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
      </div>
    ) : (
      <EmptyState
        title="Belum ada record"
        description="Informasi akan tampil ketika pengiriman dipersiapkan."
      />
    );
  const actionDisabled =
    decision.isPending ||
    reason.trim().length < 5 ||
    Number(shipment.open_tasks || 0) > 0;

  return (
    <CloudflarePageShell className="cf-shipment-detail-page">
      <Link className="back-link" href="/shipments">
        <ArrowLeft size={15} /> Kembali ke pengiriman
      </Link>
      <PageHeader
        icon={Package}
        title={value(shipment, "internal_reference")}
        description={`${value(shipment, "origin")} → ${value(shipment, "destination")}`}
        actions={
          <div className="cf-page-actions">
            <Button
              variant="secondary"
              size="sm"
              disabled={assessment.isPending}
              onClick={() => assessment.mutate()}
            >
              {assessment.isPending ? "Menilai…" : "Jalankan penilaian"}
            </Button>
            <OperationalState value={localStatus(status)} />
          </div>
        }
      />
      <div className="cf-shipment-detail-layout">
        <main className="cf-shipment-detail-main">
          <Tabs
            tabs={tabs.map((itemTab) => ({ value: itemTab, label: itemTab }))}
            value={tab}
            onValueChange={(next) => setTab(next as Tab)}
            className="detail-tabs"
            aria-label="Bagian pengiriman"
          />
          {tab === "Ringkasan" && (
            <div className="cf-shipment-overview-stack">
              <DataTableSurface
                title="Ringkasan pengiriman"
                description="Konteks yang dipakai untuk pemeriksaan dan keputusan pelepasan."
                actions={<ShieldCheck size={19} aria-hidden="true" />}
              >
                <dl className="cf-shipment-summary-grid">
                  <div>
                    <dt>Referensi pesanan</dt>
                    <dd>{value(shipment, "external_reference")}</dd>
                  </div>
                  <div>
                    <dt>Moda transportasi</dt>
                    <dd>{value(shipment, "transport_mode")}</dd>
                  </div>
                  <div>
                    <dt>Prioritas</dt>
                    <dd>{value(shipment, "priority")}</dd>
                  </div>
                  <div>
                    <dt>Tingkat risiko</dt>
                    <dd>{value(shipment, "risk_level")}</dd>
                  </div>
                  <div>
                    <dt>Mata uang</dt>
                    <dd>{value(shipment, "currency")}</dd>
                  </div>
                  <div>
                    <dt>Assessment terakhir</dt>
                    <dd>{date(shipment.last_assessed_at)}</dd>
                  </div>
                </dl>
              </DataTableSurface>
              {assessment.isError && (
                <p className="form-error" role="alert">
                  {(assessment.error as Error).message}
                </p>
              )}
              {trustedReference.isError ? (
                <StateNotice
                  tone="warning"
                  title="Referensi tepercaya belum tersedia"
                >
                  Simpan sumber tepercaya sebelum penilaian.
                </StateNotice>
              ) : (
                trustedReference.data && (
                  <DataTableSurface
                    title="Referensi tepercaya"
                    description="Snapshot sumber otoritatif yang dipakai untuk perbandingan dan gerbang pelepasan."
                  >
                    <dl className="cf-shipment-summary-grid">
                      <div>
                        <dt>Sumber</dt>
                        <dd>
                          {value(
                            trustedReference.data.reference as Row | undefined,
                            "source_system",
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt>Referensi pesanan</dt>
                        <dd>
                          {value(
                            trustedReference.data.reference as Row | undefined,
                            "order_reference",
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt>Penerima</dt>
                        <dd>
                          {value(
                            trustedReference.data.reference as Row | undefined,
                            "expected_recipient",
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt>Tujuan</dt>
                        <dd>
                          {value(
                            trustedReference.data.reference as Row | undefined,
                            "expected_destination",
                          )}
                        </dd>
                      </div>
                    </dl>
                  </DataTableSurface>
                )
              )}
              <DataTableSurface
                title="Gerbang pelepasan"
                description="Snapshot ini berasal dari backend dan menjadi sumber kebenaran keputusan pelepasan."
              >
                {gateSnapshot.isError ? (
                  <StateNotice
                    title="Snapshot gerbang pelepasan tidak tersedia."
                    tone="danger"
                  >
                    Coba lagi setelah koneksi layanan pulih.
                  </StateNotice>
                ) : gate.length ? (
                  <div className="cf-release-gate-list">
                    {gate.map((entry) => (
                      <div key={String(entry.key)}>
                        <span>{String(entry.label)}</span>
                        <OperationalState value={String(entry.state)} />
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    title="Belum ada evaluasi gerbang pelepasan"
                    description="Jalankan penilaian setelah dokumen dan referensi tersedia."
                  />
                )}
                {blockers.length ? (
                  <div className="cf-release-blocker-list" role="status">
                    <strong>Yang menahan keputusan</strong>
                    {blockers.map((item, index) => (
                      <span key={String(item.code || index)}>
                        {String(item.detail || item.code)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </DataTableSurface>
            </div>
          )}
          {tab === "Dokumen" && (
            <DataTableSurface
              title="Penyimpanan dokumen"
              description="Bukti terversi yang terikat pada pengiriman."
            >
              {rows(list("documents"), [
                ["document_type", "Jenis"],
                ["status", "Status"],
                ["created_at", "Ditambahkan"],
                ["updated_at", "Diperbarui"],
              ])}
            </DataTableSurface>
          )}
          {tab === "Barang" && (
            <DataTableSurface
              title="Barang dan komoditas"
              description="Klasifikasi dan informasi barang berbahaya yang direkam untuk pergerakan ini."
            >
              {rows(list("items"), [
                ["line_number", "Baris"],
                ["sku", "SKU"],
                ["description", "Deskripsi"],
                ["quantity", "Jumlah"],
                ["hs_code", "HS code"],
                ["dangerous_goods", "Barang berbahaya"],
              ])}
            </DataTableSurface>
          )}
          {tab === "Pihak" && (
            <DataTableSurface
              title="Pihak terkait"
              description="Entitas perdagangan yang terhubung ke pengiriman."
            >
              {rows(
                list("parties").map((row) => ({
                  ...row,
                  legal_name: (row.party as Row | undefined)?.legal_name,
                  country_code: (row.party as Row | undefined)?.country_code,
                })),
                [
                  ["role", "Peran"],
                  ["legal_name", "Pihak"],
                  ["country_code", "Negara"],
                ],
              )}
            </DataTableSurface>
          )}
          {tab === "Transport" && (
            <DataTableSurface
              title="Rencana transportasi"
              description="Leg, pengangkut, dan peralatan yang tercatat untuk pengiriman."
            >
              {rows(list("transport"), [
                ["sequence", "Leg"],
                ["mode", "Moda"],
                ["carrier", "Pengangkut"],
                ["origin", "Asal"],
                ["destination", "Tujuan"],
                ["planned_arrival", "Estimasi tiba"],
              ])}
            </DataTableSurface>
          )}
          {tab === "Jaminan" && (
            <DataTableSurface
              title="Pemeriksaan jaminan"
              description="Pemeriksaan mempertahankan sumber dan versi aturan untuk peninjauan."
            >
              {rows(list("checks"), [
                ["check_type", "Pemeriksaan"],
                ["status", "Status"],
                ["severity", "Tingkat risiko"],
                ["source", "Sumber"],
                ["completed_at", "Dievaluasi"],
              ])}
            </DataTableSurface>
          )}
          {tab === "Pengecualian" && (
            <DataTableSurface
              title="Pengecualian"
              description="Temuan yang membutuhkan resolusi terdokumentasi."
            >
              {rows(list("exceptions"), [
                ["severity", "Tingkat risiko"],
                ["summary", "Pengecualian"],
                ["status", "Status"],
                ["assigned_to", "Penanggung jawab"],
                ["due_at", "Jatuh tempo"],
              ])}
            </DataTableSurface>
          )}
          {tab === "Timeline" && (
            <DataTableSurface
              title="Linimasa pengiriman"
              description="Waktu pada record berasal dari event dan lifecycle yang tersimpan."
            >
              {rows(
                [shipment],
                [
                  ["created_at", "Dibuat"],
                  ["assessment_started_at", "Penilaian dimulai"],
                  ["last_assessed_at", "Penilaian terakhir"],
                  ["release_authorized_at", "Pelepasan diizinkan"],
                  ["dispatched_at", "Dikirim"],
                  ["closed_at", "Ditutup"],
                ],
              )}
            </DataTableSurface>
          )}
        </main>
        <ContextRail title="Konteks pengiriman">
          <RailSection title="Status saat ini">
            <OperationalState value={localStatus(status)} />
          </RailSection>
          <RailSection title="Identitas">
            <KeyValueList
              items={[
                {
                  label: "Referensi internal",
                  value: value(shipment, "internal_reference"),
                },
                {
                  label: "Referensi eksternal",
                  value: value(shipment, "external_reference"),
                },
                {
                  label: "Pemilik",
                  value: value(shipment, "owner_name", "Belum ditetapkan"),
                },
              ]}
            />
          </RailSection>
          <RailSection title="Keputusan">
            <KeyValueList
              items={[
                {
                  label: "Pemeriksaan terbuka",
                  value: String(shipment.open_tasks || 0),
                },
                { label: "Risiko", value: value(shipment, "risk_level") },
                { label: "Diperbarui", value: date(shipment.updated_at) },
              ]}
            />
          </RailSection>
          <RailSection title="Tindakan yang diizinkan">
            {canDecide ? (
              <div className="cf-rail-action-stack">
                <AppTextarea
                  label="Catatan keputusan"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Catat bukti yang mendukung keputusan"
                  minLength={5}
                  description="Minimal 5 karakter. Catatan disimpan pada record keputusan."
                />
                {decision.isError && (
                  <p role="alert" className="form-error">
                    {(decision.error as Error).message}
                  </p>
                )}
                {move.isError && (
                  <p role="alert" className="form-error">
                    {(move.error as Error).message}
                  </p>
                )}
                <Button
                  variant="secondary"
                  disabled={decision.isPending || reason.trim().length < 5}
                  onClick={() => decision.mutate("HOLD")}
                >
                  Tahan pengiriman
                </Button>
                <Button
                  disabled={actionDisabled}
                  onClick={() => decision.mutate("AUTHORIZE")}
                >
                  Otorisasi pelepasan
                </Button>
                {status === "RELEASE_AUTHORIZED" && (
                  <Button
                    disabled={move.isPending}
                    onClick={() => move.mutate("DISPATCHED")}
                  >
                    Tandai dikirim
                  </Button>
                )}
                {status === "DISPATCHED" && (
                  <Button
                    disabled={move.isPending}
                    onClick={() => move.mutate("CLOSED")}
                  >
                    Tutup pengiriman
                  </Button>
                )}
              </div>
            ) : (
              <p className="cf-rail-muted">
                Peninjau atau administrator dapat merekam keputusan pengiriman.
              </p>
            )}
          </RailSection>
        </ContextRail>
      </div>
    </CloudflarePageShell>
  );
}
