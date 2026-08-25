"use client";

import { Input } from "@cloudflare/kumo/components/input";
import { Table } from "@cloudflare/kumo/components/table";
import {
  WebhooksLogoIcon as Webhooks,
  CopyIcon as Copy,
  WarningCircleIcon as Warning,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DataTableSurface,
  EmptyState,
  LoadingState,
} from "@/components/ui/page-primitives";
import {
  OperationalState,
  StateNotice,
} from "@/components/ui/operational-primitives";
import { PageHeader } from "@/components/ui/page-header";
import {
  createWebhook,
  fetchWebhooks,
  testWebhook,
  webhookAction,
} from "@/lib/api";

type Webhook = {
  id: string;
  name: string;
  endpoint: string;
  events: string[];
  enabled: boolean;
  secret_configured: boolean;
  delivery_capability: string;
  created_at?: string;
};

export default function WebhooksPage() {
  const client = useQueryClient();
  const result = useQuery({ queryKey: ["webhooks"], queryFn: fetchWebhooks });
  const [form, setForm] = useState({
    name: "",
    endpoint: "",
    events: "shipment.created,release.decision.recorded",
  });
  const mutation = useMutation({
    mutationFn: () =>
      createWebhook({
        ...form,
        events: form.events
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      setForm({
        name: "",
        endpoint: "",
        events: "shipment.created,release.decision.recorded",
      });
      client.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
  const deliveryMutation = useMutation({
    mutationFn: testWebhook,
    onSuccess: (_, id) => {
      client.invalidateQueries({ queryKey: ["webhook-deliveries", id] });
    },
  });
  const lifecycleMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      webhookAction(id, action),
    onSuccess: () => client.invalidateQueries({ queryKey: ["webhooks"] }),
  });
  const items = useMemo(
    () => (result.data?.items || []) as Webhook[],
    [result.data],
  );
  const [secretCopied, setSecretCopied] = useState(false);
  async function copySecret() {
    await navigator.clipboard.writeText(String(mutation.data?.secret || ""));
    setSecretCopied(true);
  }

  return (
    <div className="operations-page cf-webhooks-page">
      <PageHeader
        icon={Webhooks}
        title="Webhooks"
        description="Endpoint dan kunci penandatangan untuk ruang kerja aktif. Pengiriman diproses melalui antrean pekerja."
      />
      <StateNotice
        title="Kunci penandatangan hanya ditampilkan sekali"
        tone="info"
        action={<Warning size={19} aria-hidden />}
      >
        Simpan kunci sekarang. Pengiriman memakai antrean pekerja dan HMAC.
      </StateNotice>
      <DataTableSurface
        title="Endpoint terdaftar"
        description={`${items.length} endpoint aktif. Pengiriman dibuat sebagai proses dan dapat diuji dari sini.`}
      >
        {result.isLoading ? (
          <LoadingState label="Memuat endpoint…" />
        ) : result.error ? (
          <EmptyState
            icon={<Webhooks size={18} />}
            title="Endpoint tidak dapat dimuat"
            description={
              result.error instanceof Error
                ? result.error.message
                : "Coba muat ulang webhooks."
            }
          />
        ) : !items.length ? (
          <EmptyState
            icon={<Webhooks size={18} />}
            title="Belum ada endpoint"
            description="Endpoint yang terdaftar akan muncul di sini."
          />
        ) : (
          <div className="table-scroll">
            <Table>
              <Table.Header sticky>
                <Table.Row>
                  <Table.Head>Nama</Table.Head>
                  <Table.Head>Endpoint</Table.Head>
                  <Table.Head>Jenis peristiwa</Table.Head>
                  <Table.Head>Status</Table.Head>
                  <Table.Head>Kunci penandatangan</Table.Head>
                  <Table.Head>Pengiriman</Table.Head>
                  <Table.Head>Aksi</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {items.map((item) => (
                  <Table.Row key={item.id}>
                    <Table.Cell>
                      <span className="table-cell-primary">{item.name}</span>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="cf-webhook-endpoint mono">
                        {item.endpoint}
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="cf-webhook-events">
                        {item.events.length
                          ? item.events.join(", ")
                          : "Semua event"}
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      <OperationalState
                        value={item.enabled ? "ENABLED" : "DISABLED"}
                      />
                    </Table.Cell>
                    <Table.Cell>
                      <OperationalState
                        value={
                          item.secret_configured ? "CONFIGURED" : "MISSING"
                        }
                      />
                    </Table.Cell>
                    <Table.Cell>
                      <OperationalState value={item.delivery_capability} />
                    </Table.Cell>
                    <Table.Cell>
                      <div className="cf-rail-action-stack">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => deliveryMutation.mutate(item.id)}
                          disabled={deliveryMutation.isPending}
                        >
                          {deliveryMutation.isPending &&
                          deliveryMutation.variables === item.id
                            ? "Antre…"
                            : "Uji pengiriman"}
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() =>
                            lifecycleMutation.mutate({
                              id: item.id,
                              action: item.enabled ? "disable" : "enable",
                            })
                          }
                        >
                          {item.enabled ? "Nonaktifkan" : "Aktifkan"}
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() =>
                            lifecycleMutation.mutate({
                              id: item.id,
                              action: "rotate",
                            })
                          }
                        >
                          Ganti kunci
                        </Button>
                      </div>
                    </Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </div>
        )}
      </DataTableSurface>
      {lifecycleMutation.data?.secret ? (
        <StateNotice
          title="Kunci penandatangan baru"
          tone="warning"
          action={
            <Button
              type="button"
              variant="secondary"
              size="sm"
              icon={Copy}
              onClick={() =>
                navigator.clipboard.writeText(
                  String(lifecycleMutation.data?.secret),
                )
              }
            >
              Salin
            </Button>
          }
        >
          Kunci hasil penggantian hanya ditampilkan sekali.
          <span className="cf-one-time-token mono">
            {String(lifecycleMutation.data.secret)}
          </span>
        </StateNotice>
      ) : null}
      <section className="form-panel cf-webhook-form">
        <div className="form-panel__heading">
          <h2>Tambahkan endpoint</h2>
          <p>
            Endpoint harus tervalidasi. Setelah dibuat, peristiwa dapat diuji
            melalui antrean pekerja.
          </p>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="form-grid">
            <Input
              label="Nama"
              required
              value={form.name}
              onChange={(event) =>
                setForm({ ...form, name: event.target.value })
              }
              placeholder="Pembaruan gudang"
            />
            <Input
              label="Endpoint"
              required
              type="url"
              value={form.endpoint}
              onChange={(event) =>
                setForm({ ...form, endpoint: event.target.value })
              }
              placeholder="https://example.com/outurn"
            />
            <Input
              label="Jenis peristiwa"
              description="Pisahkan nama event dengan koma."
              value={form.events}
              onChange={(event) =>
                setForm({ ...form, events: event.target.value })
              }
            />
          </div>
          {mutation.data ? (
            <StateNotice
              title="Simpan kunci penandatangan sekarang"
              tone="warning"
              action={
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  icon={Copy}
                  onClick={copySecret}
                >
                  {secretCopied ? "Tersalin" : "Salin"}
                </Button>
              }
            >
              Kunci hanya muncul sekali dan tidak dapat diambil kembali. Simpan
              secara aman di pengelola rahasia endpoint tujuan.
              <span className="cf-one-time-token mono">
                {String(mutation.data.secret)}
              </span>
            </StateNotice>
          ) : null}
          {mutation.isError ? (
            <p className="form-error">{(mutation.error as Error).message}</p>
          ) : null}
          <div className="form-panel__actions">
            <Button
              type="submit"
              variant="primary"
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Menyimpan…" : "Buat endpoint"}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
