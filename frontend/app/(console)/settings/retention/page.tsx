"use client";

import { startTransition, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { LoadingState } from "@/components/ui/page-primitives";
import { Input } from "@cloudflare/kumo/components/input";
import {
  fetchWorkspaceSettings,
  retentionCleanup,
  retentionDryRun,
  saveWorkspaceSettings,
} from "@/lib/api";
import { useSettingsCopy } from "@/components/settings/settings-copy";

export default function RetentionSettingsPage() {
  const { t } = useSettingsCopy();
  const client = useQueryClient();
  const [form, setForm] = useState({
    audit_days: "365",
    document_days: "365",
    job_days: "90",
    webhook_days: "90",
  });
  const [saved, setSaved] = useState(false);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const settings = useQuery({
    queryKey: ["workspace-settings"],
    queryFn: fetchWorkspaceSettings,
  });
  const saveMutation = useMutation({
    mutationFn: () => saveWorkspaceSettings({ retention: form }),
    onSuccess: () => {
      setSaved(true);
      client.invalidateQueries({ queryKey: ["workspace-settings"] });
      window.setTimeout(() => setSaved(false), 2500);
    },
  });
  const dryRun = useMutation({
    mutationFn: retentionDryRun,
    onSuccess: setReport,
  });
  const cleanup = useMutation({
    mutationFn: retentionCleanup,
    onSuccess: setReport,
  });

  useEffect(() => {
    if (settings.data) {
      const values = settings.data.settings as
        Record<string, unknown> | undefined;
      if (values?.retention)
        startTransition(() =>
          setForm((current) => ({
            ...current,
            ...(values.retention as typeof current),
          })),
        );
    }
  }, [settings.data]);

  return (
    <div className="operations-page">
      <PageHeader
        title={t.retention}
        description={t.retentionPageDescription}
      />
      {settings.isPending ? (
        <LoadingState
          label="Memuat kebijakan retensi…"
          className="page-loading"
        />
      ) : null}
      {settings.isError ? (
        <p className="form-error" role="alert">
          Kebijakan retensi tidak dapat dimuat.{" "}
          {(settings.error as Error).message}
        </p>
      ) : null}
      <form
        className="form-panel settings-form"
        onSubmit={(event) => {
          event.preventDefault();
          saveMutation.mutate();
        }}
      >
        <div className="form-grid">
          <Input
            label={t.activityHistoryDays}
            type="number"
            min="30"
            value={form.audit_days}
            onChange={(event) =>
              setForm({ ...form, audit_days: event.target.value })
            }
          />
          <Input
            label={t.documentMetadataDays}
            type="number"
            min="30"
            value={form.document_days}
            onChange={(event) =>
              setForm({ ...form, document_days: event.target.value })
            }
          />
          <Input
            label={t.processingHistoryDays}
            type="number"
            min="7"
            value={form.job_days}
            onChange={(event) =>
              setForm({ ...form, job_days: event.target.value })
            }
          />
          <Input
            label={t.deliveryHistoryDays}
            type="number"
            min="7"
            value={form.webhook_days}
            onChange={(event) =>
              setForm({ ...form, webhook_days: event.target.value })
            }
          />
        </div>
        <p className="muted-copy">{t.retentionHint}</p>
        <div className="form-panel__actions">
          <Button
            type="submit"
            variant="primary"
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending ? "Menyimpan…" : t.saveRetention}
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => dryRun.mutate()}
            disabled={dryRun.isPending}
          >
            {dryRun.isPending ? "Menghitung…" : "Dry-run cleanup"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => cleanup.mutate()}
            disabled={cleanup.isPending}
          >
            {cleanup.isPending ? "Membersihkan…" : "Jalankan cleanup"}
          </Button>
          {saveMutation.isError ? (
            <span className="form-error" role="alert">
              {(saveMutation.error as Error).message}
            </span>
          ) : null}
          {dryRun.isError || cleanup.isError ? (
            <span className="form-error" role="alert">
              {((dryRun.error || cleanup.error) as Error).message}
            </span>
          ) : null}
          {saved && (
            <span className="form-success" role="status">
              {t.retentionSaved}
            </span>
          )}
        </div>
      </form>
      {report ? (
        <section className="data-panel retention-report" aria-live="polite">
          <div className="data-panel__heading">
            <h2>{report.mutated ? "Cleanup selesai" : "Preview cleanup"}</h2>
            <p>
              Legal hold aktif tidak ikut dihitung sebagai kandidat penghapusan.
            </p>
          </div>
          <pre className="cf-safe-config">
            {JSON.stringify(report.deleted || report.candidates || {}, null, 2)}
          </pre>
        </section>
      ) : null}
    </div>
  );
}
