"use client";

import { Dialog, DialogRoot } from "@cloudflare/kumo/components/dialog";
import { Input } from "@cloudflare/kumo/components/input";
import { Table } from "@cloudflare/kumo/components/table";
import {
  PlusIcon as Plus,
  UsersThreeIcon as UsersThree,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useDeferredValue, useState } from "react";
import { ActionLink, Button } from "@/components/ui/button";
import {
  operationalTextLabel,
  OperationalState,
  StateNotice,
} from "@/components/ui/operational-primitives";
import { PageHeader } from "@/components/ui/page-header";
import {
  CloudflarePageShell,
  DataTableSurface,
  EmptyState,
  FilterBar,
  LoadingState,
  SearchField,
} from "@/components/ui/page-primitives";
import { AppSelect } from "@/components/ui/select";
import { createParty, fetchOperationsList } from "@/lib/api";

type Row = Record<string, unknown>;

export default function PartiesPage() {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    legal_name: "",
    trade_name: "",
    country_code: "ID",
    external_identifier: "",
    tax_identifier: "",
    role: "OTHER",
    address: "",
  });
  const deferredQuery = useDeferredValue(query);
  const result = useQuery({
    queryKey: ["parties", deferredQuery],
    queryFn: () =>
      fetchOperationsList(
        "/parties",
        deferredQuery ? { q: deferredQuery } : undefined,
      ),
  });
  const mutation = useMutation({
    mutationFn: () =>
      createParty({
        ...form,
        country_code: form.country_code || null,
        trade_name: form.trade_name || null,
        external_identifier: form.external_identifier || null,
        tax_identifier: form.tax_identifier || null,
        address: form.address || null,
      }),
    onSuccess: () => {
      setOpen(false);
      setForm({
        legal_name: "",
        trade_name: "",
        country_code: "ID",
        external_identifier: "",
        tax_identifier: "",
        role: "OTHER",
        address: "",
      });
      client.invalidateQueries({ queryKey: ["parties"] });
    },
  });
  const rows = result.data?.items || [];
  const notConfigured = rows.some((row) =>
    ["NOT_CONFIGURED", "NOT_RUN"].includes(String(row.screening)),
  );
  return (
    <CloudflarePageShell className="cf-parties-page">
      <PageHeader
        icon={UsersThree}
        title="Pihak terkait"
        description="Tinjau entitas perdagangan yang berhubungan dengan pengiriman dan status penyaringan yang tercatat."
        actions={
          <Button icon={Plus} onClick={() => setOpen(true)}>
            Tambah pihak
          </Button>
        }
      />
      <FilterBar label="Cari pihak terkait">
        <SearchField
          value={query}
          onChange={setQuery}
          placeholder="Cari nama legal atau identitas"
          ariaLabel="Cari pihak terkait"
        />
        <span className="cf-metadata">{rows.length} entitas</span>
      </FilterBar>
      {result.isPending ? (
        <LoadingState label="Memuat pihak terkait…" className="page-loading" />
      ) : result.isError ? (
        <StateNotice
          title="Daftar pihak terkait tidak tersedia saat ini."
          tone="danger"
        >
          Coba lagi setelah koneksi layanan pulih.
        </StateNotice>
      ) : (
        <>
          {notConfigured && (
            <StateNotice tone="warning" title="Penyaringan belum dikonfigurasi">
              Konfigurasi penyedia diperlukan sebelum hasil dibuat.
            </StateNotice>
          )}
          <DataTableSurface
            title="Daftar entitas"
            description="Peran dan identitas ditampilkan dari pihak yang tersimpan."
          >
            {rows.length ? (
              <div className="table-scroll">
                <Table>
                  <Table.Header sticky>
                    <Table.Row>
                      <Table.Head>Entitas</Table.Head>
                      <Table.Head>Peran</Table.Head>
                      <Table.Head>Negara</Table.Head>
                      <Table.Head>Identifier</Table.Head>
                      <Table.Head>Penyaringan</Table.Head>
                      <Table.Head>Pengiriman</Table.Head>
                      <Table.Head>
                        <span className="sr-only">Aksi</span>
                      </Table.Head>
                    </Table.Row>
                  </Table.Header>
                  <Table.Body>
                    {rows.map((row) => (
                      <Table.Row key={String(row.id)}>
                        <Table.Cell>
                          <span className="table-cell-primary">
                            {String(row.legal_name || "—")}
                          </span>
                          <small>{String(row.trade_name || "")}</small>
                        </Table.Cell>
                        <Table.Cell>
                          {operationalTextLabel(String(row.role || "—"))}
                        </Table.Cell>
                        <Table.Cell>
                          {String(row.country_code || "—")}
                        </Table.Cell>
                        <Table.Cell>
                          {String(
                            row.external_identifier ||
                              row.tax_identifier ||
                              "—",
                          )}
                        </Table.Cell>
                        <Table.Cell>
                          <OperationalState
                            value={String(row.screening || "NOT_CONFIGURED")}
                          />
                        </Table.Cell>
                        <Table.Cell>
                          {String(row.shipment_count || 0)}
                        </Table.Cell>
                        <Table.Cell>
                          {row.shipment_id ? (
                            <ActionLink
                              href={`/shipments/${String(row.shipment_id)}`}
                              variant="ghost"
                            >
                              Buka
                            </ActionLink>
                          ) : (
                            <span className="cf-metadata">—</span>
                          )}
                        </Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table>
              </div>
            ) : (
              <EmptyState
                icon={<UsersThree size={20} />}
                title="Belum ada pihak terkait"
                description="Pihak akan tampil ketika direkam pada pengiriman."
              />
            )}
          </DataTableSurface>
        </>
      )}
      <DialogRoot open={open} onOpenChange={setOpen}>
        <Dialog className="cf-register-dialog">
          <Dialog.Title>Tambah pihak</Dialog.Title>
          <Dialog.Description>
            Rekam entitas perdagangan yang akan dipakai pada shipment dan
            screening.
          </Dialog.Description>
          <form
            className="dialog-form"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            <div className="form-grid">
              <Input
                label="Nama legal"
                required
                value={form.legal_name}
                onChange={(event) =>
                  setForm({ ...form, legal_name: event.target.value })
                }
              />
              <Input
                label="Nama dagang"
                description="Opsional"
                value={form.trade_name}
                onChange={(event) =>
                  setForm({ ...form, trade_name: event.target.value })
                }
              />
              <Input
                label="Kode negara"
                required
                minLength={2}
                maxLength={2}
                value={form.country_code}
                onChange={(event) =>
                  setForm({
                    ...form,
                    country_code: event.target.value.toUpperCase(),
                  })
                }
              />
              <label>
                Peran
                <AppSelect
                  ariaLabel="Peran pihak"
                  value={form.role}
                  onValueChange={(role) => setForm({ ...form, role })}
                  options={[
                    { value: "SHIPPER", label: "Pengirim" },
                    { value: "CONSIGNEE", label: "Penerima" },
                    { value: "CARRIER", label: "Pengangkut" },
                    { value: "OTHER", label: "Lainnya" },
                  ]}
                />
              </label>
              <Input
                label="Identifier eksternal"
                description="Opsional"
                value={form.external_identifier}
                onChange={(event) =>
                  setForm({ ...form, external_identifier: event.target.value })
                }
              />
              <Input
                label="Identitas pajak"
                description="Opsional"
                value={form.tax_identifier}
                onChange={(event) =>
                  setForm({ ...form, tax_identifier: event.target.value })
                }
              />
            </div>
            <Input
              label="Alamat"
              description="Opsional"
              value={form.address}
              onChange={(event) =>
                setForm({ ...form, address: event.target.value })
              }
            />
            {mutation.isError && (
              <p className="form-error" role="alert">
                {(mutation.error as Error).message}
              </p>
            )}
            <div className="form-panel__actions">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setOpen(false)}
              >
                Batal
              </Button>
              <Button
                type="submit"
                disabled={
                  mutation.isPending || form.legal_name.trim().length < 2
                }
              >
                {mutation.isPending ? "Menyimpan…" : "Simpan pihak"}
              </Button>
            </div>
          </form>
        </Dialog>
      </DialogRoot>
    </CloudflarePageShell>
  );
}
