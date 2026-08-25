"use client";

import { startTransition, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Switch } from "@cloudflare/kumo/components/switch";
import { PageHeader } from "@/components/ui/page-header";
import { LoadingState } from "@/components/ui/page-primitives";
import { fetchWorkspaceSettings, saveWorkspaceSettings } from "@/lib/api";
import { useSettingsCopy } from "@/components/settings/settings-copy";

const optionKeys = [
  "task_assigned",
  "critical_exception",
  "task_overdue",
  "evidence_requested",
  "release_invalidated",
] as const;

export default function NotificationSettingsPage() {
  const { t } = useSettingsCopy();
  const client = useQueryClient();
  const labels = {
    task_assigned: t.taskAssigned,
    critical_exception: t.criticalException,
    task_overdue: t.taskOverdue,
    evidence_requested: t.evidenceRequested,
    release_invalidated: t.releaseNeedsReview,
  };
  const [form, setForm] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(optionKeys.map((key) => [key, true])),
  );
  const [saved, setSaved] = useState(false);
  const settings = useQuery({
    queryKey: ["workspace-settings"],
    queryFn: fetchWorkspaceSettings,
  });
  const saveMutation = useMutation({
    mutationFn: () => saveWorkspaceSettings({ notifications: form }),
    onSuccess: () => {
      setSaved(true);
      client.invalidateQueries({ queryKey: ["workspace-settings"] });
      window.setTimeout(() => setSaved(false), 2500);
    },
  });

  useEffect(() => {
    const savedValues = (
      settings.data?.settings as Record<string, unknown> | undefined
    )?.notifications;
    if (savedValues && typeof savedValues === "object")
      startTransition(() =>
        setForm((current) => ({
          ...current,
          ...(savedValues as Record<string, boolean>),
        })),
      );
  }, [settings.data]);

  return (
    <div className="operations-page">
      <PageHeader
        title={t.notifications}
        description={t.notificationsPageDescription}
      />
      {settings.isPending ? (
        <LoadingState
          label="Memuat preferensi notifikasi…"
          className="page-loading"
        />
      ) : null}
      {settings.isError ? (
        <p className="form-error" role="alert">
          Preferensi notifikasi tidak dapat dimuat.{" "}
          {(settings.error as Error).message}
        </p>
      ) : null}
      <form
        className="data-panel settings-check-list settings-form"
        onSubmit={(event) => {
          event.preventDefault();
          saveMutation.mutate();
        }}
      >
        {optionKeys.map((key) => (
          <Switch
            key={key}
            label={labels[key]}
            checked={Boolean(form[key])}
            onCheckedChange={(checked) =>
              setForm({ ...form, [key]: Boolean(checked) })
            }
          />
        ))}
        <p className="muted-copy">{t.notificationPreferencesHint}</p>
        <div className="form-panel__actions">
          <Button
            type="submit"
            variant="primary"
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending ? "Menyimpan…" : t.saveNotifications}
          </Button>
          {saveMutation.isError ? (
            <span className="form-error" role="alert">
              {(saveMutation.error as Error).message}
            </span>
          ) : null}
          {saved && (
            <span className="form-success" role="status">
              {t.notificationsSaved}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}
