"use client";

import { ActivityIcon as Activity, CheckCircleIcon as Check, CaretRightIcon as ArrowRight } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { EmptyState, CloudflarePageShell, DataTableSurface, LoadingState } from "@/components/ui/page-primitives";
import { PageHeader } from "@/components/ui/page-header";
import { StateNotice } from "@/components/ui/operational-primitives";
import { fetchNotifications, markNotificationRead } from "@/lib/api";

function notificationDate(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
}

export default function NotificationsPage() {
  const router = useRouter();
  const client = useQueryClient();
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: () => fetchNotifications() });
  const readNotification = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });

  async function openNotification(item: Record<string, unknown>) {
    const id = String(item.id || "");
    if (!item.read_at && id) await readNotification.mutateAsync(id);
    if (item.href) router.push(String(item.href));
  }

  const items = notifications.data?.items || [];
  return (
    <CloudflarePageShell className="cf-notifications-page">
      <PageHeader
        icon={Activity}
        title="Notifikasi"
        description="Peringatan operasional terbaru untuk ruang kerja ini."
      />
      {notifications.isError ? (
        <StateNotice title="Notifikasi tidak dapat dimuat" tone="danger">
          Coba lagi setelah koneksi layanan pulih.
        </StateNotice>
      ) : null}
      {readNotification.isError ? (
        <StateNotice title="Notifikasi belum diperbarui" tone="warning">
          Coba lagi sebentar lagi.
        </StateNotice>
      ) : null}
      <DataTableSurface
        title="Pusat notifikasi"
        actions={
          <span className="cf-metadata">
            {notifications.data?.unread || 0} belum dibaca
          </span>
        }
      >
        {notifications.isPending ? (
          <LoadingState label="Memuat notifikasi…" />
        ) : items.length ? (
          <ul className="cf-notification-list" aria-live="polite">
            {items.map((item) => {
              const read = Boolean(item.read_at);
              const hasAction = Boolean(item.href) || !read;
              return (
                <li
                  className={`cf-notification-list__item ${read ? "is-read" : "is-unread"}`}
                  key={String(item.id)}
                >
                  <div className="cf-notification-list__marker" aria-hidden="true">
                    {read ? <Check size={14} /> : <span />}
                  </div>
                  <div className="cf-notification-list__copy">
                    <span className="cf-notification-list__title">
                      {String(item.title || "Notifikasi")}
                    </span>
                    {item.body ? <p>{String(item.body)}</p> : null}
                    <small>{notificationDate(item.created_at)}</small>
                  </div>
                  {hasAction ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={item.href ? ArrowRight : Check}
                      disabled={readNotification.isPending}
                      onClick={() => void openNotification(item)}
                    >
                      {item.href ? "Buka" : "Tandai dibaca"}
                    </Button>
                  ) : (
                    <span className="cf-notification-list__read-label">
                      Sudah dibaca
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState
            icon={<Activity size={20} />}
            title="Belum ada notifikasi"
            description="Peringatan operasional baru akan muncul di sini."
          />
        )}
      </DataTableSurface>
    </CloudflarePageShell>
  );
}
