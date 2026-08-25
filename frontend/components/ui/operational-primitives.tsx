import { Badge } from "@cloudflare/kumo/components/badge";
import { Banner } from "@cloudflare/kumo/components/banner";
import type { ReactNode } from "react";

function join(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

const OPERATIONAL_STATUS_LABELS: Record<string, string> = {
  CLEAR: "Lulus",
  REVIEW: "Perlu ditinjau",
  HOLD: "Ditahan",
  FAILED: "Gagal",
  OPEN: "Terbuka",
  IN_PROGRESS: "Sedang diproses",
  RESOLVED: "Selesai",
  PENDING: "Menunggu",
  PROPOSED: "Diusulkan",
  QUEUED: "Dalam antrean",
  RUNNING: "Berjalan",
  SUCCEEDED: "Berhasil",
  COMPLETED: "Selesai",
  AUTHORIZED: "Diotorisasi",
  RELEASE_AUTHORIZED: "Siap dirilis",
  RELEASE_INVALIDATED: "Pelepasan perlu ditinjau",
  RELEASE_PENDING_APPROVAL: "Menunggu persetujuan kedua",
  PENDING_SECOND_APPROVAL: "Menunggu persetujuan kedua",
  DISPATCHED: "Dikirim",
  CLOSED: "Ditutup",
  REVIEW_REQUIRED: "Perlu ditinjau",
  DOCUMENTS_REQUIRED: "Dokumen diperlukan",
  NOT_CONFIGURED: "Belum dikonfigurasi",
  NOT_RUN: "Belum dijalankan",
  NOT_APPLICABLE: "Tidak berlaku",
  INVALIDATED: "Dibatalkan",
  DEAD_LETTER: "Gagal permanen",
  AUTHORIZE: "Otorisasi pelepasan",
  "PENDING SECOND APPROVAL": "Menunggu persetujuan kedua",
  HEALTHY: "Sehat",
  DEGRADED: "Menurun",
  NOT_RUNNING: "Tidak berjalan",
  CONFIGURED: "Terkonfigurasi",
  MISSING: "Belum tersedia",
  REQUIRES_REVIEW: "Perlu ditinjau",
  UNKNOWN: "Belum diketahui",
  LOW: "Rendah",
  MEDIUM: "Sedang",
  HIGH: "Tinggi",
  CRITICAL: "Kritis",
  PLANNED: "Terjadwal",
  DRAFT: "Draf",
  PUBLISHED: "Diterbitkan",
  ACTIVE: "Aktif",
  INACTIVE: "Tidak aktif",
  DISABLED: "Dinonaktifkan",
  ENABLED: "Aktif",
  APPROVED: "Disetujui",
  REVOKED: "Dicabut",
  REJECTED: "Ditolak",
  FALSE_POSITIVE: "Bukan kecocokan",
  MATCH: "Cocok",
  PERLU_PERHATIAN: "Perlu perhatian",
  TERHUBUNG: "Terhubung",
  DOCUMENT: "Dokumen",
  COUNTRY: "Negara",
  SKU: "SKU",
};

const OPERATIONAL_TEXT_LABELS: Record<string, string> = {
  PARTY_SCREENING: "Penyaringan pihak",
  DOCUMENT_CHECK: "Pemeriksaan dokumen",
  DOCUMENT_RECONCILIATION: "Rekonsiliasi dokumen",
  DANGEROUS_GOODS: "Barang berbahaya",
  SHIPPER: "Pengirim",
  CONSIGNEE: "Penerima",
  CARRIER: "Pengangkut",
  OTHER: "Lainnya",
  ERP: "ERP",
  WMS: "WMS",
  ROAD: "Darat",
  SEA: "Laut",
  AIR: "Udara",
  RAIL: "Rel",
  NEEDS_REVIEW: "Perlu ditinjau",
  REQUIRES_REVIEW: "Perlu ditinjau",
  MENUNGGU_AKTIVITAS: "Menunggu aktivitas",
  BELUM_AKTIF: "Belum aktif",
};

export function operationalStatusLabel(value: string | null | undefined) {
  const normalized = String(value || "")
    .trim()
    .toUpperCase();
  if (!normalized) return "—";
  return (
    OPERATIONAL_STATUS_LABELS[normalized] ||
    normalized
      .replaceAll("_", " ")
      .toLowerCase()
      .replace(/(^|\s)\S/g, (letter) => letter.toUpperCase())
  );
}

export function operationalTextLabel(value: string | null | undefined) {
  const normalized = String(value || "")
    .trim()
    .toUpperCase();
  if (!normalized) return "—";
  return (
    OPERATIONAL_TEXT_LABELS[normalized] ||
    OPERATIONAL_STATUS_LABELS[normalized] ||
    normalized
      .replaceAll("_", " ")
      .toLowerCase()
      .replace(/(^|\s)\S/g, (letter) => letter.toUpperCase())
  );
}

function tone(value: string) {
  const normalized = value.toLowerCase();
  if (/(hold|failed|error|dead_letter|invalidated|critical|high|rejected)/.test(normalized))
    return "error" as const;
  if (
    /(review|pending|proposed|medium|not_configured|not_running|warning)/.test(normalized)
  )
    return "warning" as const;
  if (/(clear|authorized|complete|success|low|resolved)/.test(normalized))
    return "success" as const;
  return "neutral" as const;
}

export function OperationalState({
  value,
  className,
}: {
  value: string | null | undefined;
  className?: string;
}) {
  const label = operationalStatusLabel(value);
  return (
    <span className="cf-status-badge" title={label} aria-label={label}>
      <Badge
        appearance="dot"
        variant={tone(String(value || ""))}
        className={className}
      >
        {label}
      </Badge>
    </span>
  );
}

export function StateNotice({
  title,
  children,
  tone: noticeTone = "info",
  action,
}: {
  title: ReactNode;
  children: ReactNode;
  tone?: "info" | "warning" | "danger";
  action?: ReactNode;
}) {
  const variant =
    noticeTone === "danger"
      ? "error"
      : noticeTone === "warning"
        ? "alert"
        : "default";
  return (
    <Banner
      className={join("cf-state-notice", `cf-state-notice--${noticeTone}`)}
      variant={variant}
      size="sm"
      title={typeof title === "string" ? title : undefined}
      description={
        typeof title === "string" ? (
          children
        ) : (
          <>
        <span className="cf-state-notice__title-inline">{title}</span> {children}
          </>
        )
      }
      action={action}
    />
  );
}

export function ContextRail({
  children,
  className,
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
}) {
  return (
    <aside
      className={join("cf-context-rail", className)}
      aria-label={typeof title === "string" ? title : "Konteks pengiriman"}
    >
      {title && <h2 className="cf-context-rail__title">{title}</h2>}
      {children}
    </aside>
  );
}

export function RailSection({
  title,
  children,
}: {
  title: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="cf-context-rail__section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

export function KeyValueList({
  items,
}: {
  items: Array<{ label: ReactNode; value: ReactNode }>;
}) {
  return (
    <dl className="cf-key-value-list">
      {items.map((item, index) => (
        <div key={index}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function LifecycleTrack({
  steps,
}: {
  steps: Array<{
    label: string;
    detail?: ReactNode;
    state: "complete" | "current" | "blocked" | "future";
  }>;
}) {
  const lifecycleLabels: Record<string, string> = {
    PROPOSED: "Diusulkan",
    "PENDING SECOND APPROVAL": "Menunggu persetujuan kedua",
    AUTHORIZED: "Diotorisasi",
    "INVALIDATED / REJECTED": "Dibatalkan atau ditolak",
  };
  return (
    <ol className="cf-lifecycle-track">
      {steps.map((step) => (
        <li
          className={`cf-lifecycle-track__step cf-lifecycle-track__step--${step.state}`}
          key={step.label}
        >
          <span className="cf-lifecycle-track__marker" aria-hidden />
          <div>
            <p>{lifecycleLabels[step.label] || step.label}</p>
            {step.detail && <small>{step.detail}</small>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function MetricCell({
  label,
  value,
  detail,
}: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="cf-metric-cell">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}
