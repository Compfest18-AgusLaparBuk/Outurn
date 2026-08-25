"use client";

import { ClockCounterClockwiseIcon as ClockCounterClockwise } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/ui/page-header";
import {
  CloudflarePageShell,
  EmptyState,
  LoadingState,
} from "@/components/ui/page-primitives";
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
      <section className="data-panel data-panel--wide">
        <div className="data-panel__header">
          <div>
            <h2>Aktivitas terbaru</h2>
            <p>
              Hanya metadata rute yang aman disimpan; isi dokumen tidak pernah
              disimpan di browser.
            </p>
          </div>
        </div>
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
                  <strong>{String(item.label)}</strong>
                  <small>
                    {String(item.object_type)} ·{" "}
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
      </section>
    </CloudflarePageShell>
  );
}
