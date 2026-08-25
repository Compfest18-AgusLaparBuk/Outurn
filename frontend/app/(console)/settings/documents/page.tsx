"use client";

import { startTransition, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@cloudflare/kumo/components/checkbox";
import { PageHeader } from "@/components/ui/page-header";
import { LoadingState } from "@/components/ui/page-primitives";
import { fetchWorkspaceSettings, saveWorkspaceSettings } from "@/lib/api";
import { useSettingsCopy } from "@/components/settings/settings-copy";

export default function DocumentSettingsPage() {
  const { t } = useSettingsCopy();
  const client = useQueryClient();
  const [form, setForm] = useState({
    require_invoice: true,
    require_packing_list: true,
    require_delivery_order: true,
    allow_replacement: true,
  });
  const [saved, setSaved] = useState(false);
  const settings = useQuery({
    queryKey: ["workspace-settings"],
    queryFn: fetchWorkspaceSettings,
  });
  const saveMutation = useMutation({
    mutationFn: () => saveWorkspaceSettings({ documents: form }),
    onSuccess: () => {
      setSaved(true);
      client.invalidateQueries({ queryKey: ["workspace-settings"] });
      window.setTimeout(() => setSaved(false), 2500);
    },
  });
  useEffect(() => {
    const values = settings.data?.settings as
      Record<string, unknown> | undefined;
    if (values?.documents)
      startTransition(() =>
        setForm((current) => ({
          ...current,
          ...(values.documents as typeof current),
        })),
      );
  }, [settings.data]);

  return (
    <div className="operations-page">
      <PageHeader
        title={t.documentPolicy}
        description={t.documentPageDescription}
      />
      {settings.isPending ? (
        <LoadingState
          label="Memuat kebijakan dokumen…"
          className="page-loading"
        />
      ) : null}
      {settings.isError ? (
        <p className="form-error" role="alert">
          Kebijakan dokumen tidak dapat dimuat.{" "}
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
        <Checkbox
          label={t.requireCommercialInvoice}
          checked={form.require_invoice}
          onCheckedChange={(checked) =>
            setForm({ ...form, require_invoice: Boolean(checked) })
          }
        />
        <Checkbox
          label={t.requirePackingList}
          checked={form.require_packing_list}
          onCheckedChange={(checked) =>
            setForm({ ...form, require_packing_list: Boolean(checked) })
          }
        />
        <Checkbox
          label={t.requireDeliveryOrder}
          checked={form.require_delivery_order}
          onCheckedChange={(checked) =>
            setForm({ ...form, require_delivery_order: Boolean(checked) })
          }
        />
        <Checkbox
          label={t.allowReplacementHistory}
          checked={form.allow_replacement}
          onCheckedChange={(checked) =>
            setForm({ ...form, allow_replacement: Boolean(checked) })
          }
        />
        <p className="muted-copy">{t.documentPolicyHint}</p>
        <div className="form-panel__actions">
          <Button
            type="submit"
            variant="primary"
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending ? "Menyimpan…" : t.saveDocumentPolicy}
          </Button>
          {saveMutation.isError ? (
            <span className="form-error" role="alert">
              {(saveMutation.error as Error).message}
            </span>
          ) : null}
          {saved && (
            <span className="form-success" role="status">
              {t.policySaved}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}
