"use client";

import { ClockCounterClockwiseIcon as ClockCounterClockwise } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/ui/page-header";
import {
  CloudflarePageShell,
  DataTableSurface,
  EmptyState,
  LoadingState,
} from "@/components/ui/page-primitives";
import { operationalTextLabel } from "@/components/ui/operational-primitives";
import { fetchRecents } from "@/lib/api";

export default function RecentsPage() {
  const result = useQuery({ queryKey: ["recents"], queryFn: fetchRecents });
  const items = result.data?.items || [];
  return (
    <CloudflarePageShell className="cf-recents-page">
      <PageHeader
        icon={ClockCounterClockwise}
        title="Terakhir dibuka"
        description="Kembali ke pekerjaan pengiriman, bukti, dan keputusan yang baru saja Anda buka."
      />
      <DataTableSurface
        className="data-panel--wide"
        title="Aktivitas terbaru"
        description="Hanya metadata rute yang aman disimpan; isi dokumen tidak pernah disimpan di browser."
      >
        {result.isPending ? (
          <LoadingState label="Memuat aktivitas terbaru…" />
        ) : items.length ? (
          <div className="activity-list">
            {items.map((item) => (
              <Link
                className="activity-row"
                href={String(item.href)}
                key={String(item.id)}
              >
                <div>
                  <span className="activity-row__title">{String(item.label)}</span>
                  <small>
                    {operationalTextLabel(String(item.object_type))} ·{" "}
                    {new Date(String(item.viewed_at)).toLocaleString("id-ID")}
                  </small>
                </div>
                <span aria-hidden="true">›</span>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Belum ada aktivitas terbaru"
            description="Buka pengiriman, dokumen, pengecualian, atau keputusan pelepasan untuk melihatnya di sini."
          />
        )}
      </DataTableSurface>
    </CloudflarePageShell>
  );
}
