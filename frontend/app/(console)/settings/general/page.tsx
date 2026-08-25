"use client";

import { startTransition, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { LoadingState } from "@/components/ui/page-primitives";
import { AppSelect } from "@/components/ui/select";
import { Input } from "@cloudflare/kumo/components/input";
import { fetchWorkspaceSettings, saveWorkspaceSettings } from "@/lib/api";
import { useSettingsCopy } from "@/components/settings/settings-copy";

export default function GeneralSettingsPage() {
  const { t } = useSettingsCopy();
  const client = useQueryClient();
  const [form, setForm] = useState({
    name: "",
    default_timezone: "UTC",
    default_locale: "en-GB",
    default_currency: "USD",
  });
  const [saved, setSaved] = useState(false);
  const settings = useQuery({
    queryKey: ["workspace-settings"],
    queryFn: fetchWorkspaceSettings,
  });
  const saveMutation = useMutation({
    mutationFn: () => saveWorkspaceSettings(form),
    onSuccess: () => {
      setSaved(true);
      client.invalidateQueries({ queryKey: ["workspace-settings"] });
      window.setTimeout(() => setSaved(false), 2500);
    },
  });

  useEffect(() => {
    if (settings.data) {
      const data = settings.data;
      const organization = data.organization as
        Record<string, unknown> | undefined;
      if (organization) {
        startTransition(() =>
          setForm({
            name: String(organization.name || ""),
            default_timezone: String(organization.default_timezone || "UTC"),
            default_locale: String(organization.default_locale || "en-GB"),
            default_currency: String(organization.default_currency || "USD"),
          }),
        );
      }
    }
  }, [settings.data]);

  return (
    <div className="operations-page">
      <PageHeader title={t.general} description={t.generalPageDescription} />
      {settings.isPending ? (
        <LoadingState
          label="Memuat pengaturan workspace…"
          className="page-loading"
        />
      ) : null}
      {settings.isError ? (
        <p className="form-error" role="alert">
          Pengaturan workspace tidak dapat dimuat.{" "}
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
            label={t.workspaceName}
            required
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <AppSelect
            ariaLabel={t.timezone}
            label={t.timezone}
            value={form.default_timezone}
            onValueChange={(default_timezone) =>
              setForm({ ...form, default_timezone })
            }
            options={[
              { value: "UTC", label: "UTC" },
              { value: "Asia/Jakarta", label: "Asia/Jakarta" },
              { value: "Europe/London", label: "Europe/London" },
              { value: "America/New_York", label: "America/New_York" },
            ]}
          />
          <AppSelect
            ariaLabel={t.locale}
            label={t.locale}
            value={form.default_locale}
            onValueChange={(default_locale) =>
              setForm({ ...form, default_locale })
            }
            options={[
              { value: "en-GB", label: "English (United Kingdom)" },
              { value: "id-ID", label: "Bahasa Indonesia" },
            ]}
          />
          <Input
            label={t.currency}
            maxLength={8}
            value={form.default_currency}
            onChange={(event) =>
              setForm({
                ...form,
                default_currency: event.target.value.toUpperCase(),
              })
            }
          />
        </div>
        <div className="form-panel__actions">
          <Button
            type="submit"
            variant="primary"
            disabled={saveMutation.isPending || !form.name.trim()}
          >
            {saveMutation.isPending ? "Menyimpan…" : t.saveChanges}
          </Button>
          {saveMutation.isError ? (
            <span className="form-error" role="alert">
              {(saveMutation.error as Error).message}
            </span>
          ) : null}
          {saved && (
            <span className="form-success" role="status">
              {t.saved}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}
