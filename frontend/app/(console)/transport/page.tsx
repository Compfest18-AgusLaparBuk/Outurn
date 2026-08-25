"use client";

import { Dialog, DialogRoot } from "@cloudflare/kumo/components/dialog";
import { Input } from "@cloudflare/kumo/components/input";
import { Table } from "@cloudflare/kumo/components/table";
import { PackageIcon as Truck, PlusIcon as Plus } from "@phosphor-icons/react";
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
import { AppCombobox, AppSelect } from "@/components/ui/select";
import {
  createTransport,
  fetchOperationsList,
  fetchShipments,
} from "@/lib/api";

function date(value: unknown) {
  return value ? new Date(String(value)).toLocaleString("id-ID") : "—";
}
function reference(row: Record<string, unknown>) {
  return String(
    row.voyage || row.flight || row.vehicle_reference || row.vessel || "—",
  );
}

export default function TransportPage() {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    shipment_id: "",
    sequence: "1",
    mode: "Road",
    carrier: "",
    origin: "",
    destination: "",
    planned_departure: "",
    planned_arrival: "",
    vessel: "",
    voyage: "",
    flight: "",
    vehicle_reference: "",
  });
  const deferredQuery = useDeferredValue(query);
  const result = useQuery({
    queryKey: ["transport", deferredQuery],
    queryFn: () =>
      fetchOperationsList(
        "/transport",
        deferredQuery ? { q: deferredQuery } : undefined,
      ),
  });
  const shipments = useQuery({
    queryKey: ["shipments", "transport-create"],
    queryFn: () => fetchShipments(new URLSearchParams("page_size=100")),
    enabled: open,
  });
  const mutation = useMutation({
    mutationFn: () => {
      if (!form.shipment_id)
        throw new Error("Pilih pengiriman terlebih dahulu.");
      const iso = (value: string) =>
        value ? new Date(value).toISOString() : null;
      return createTransport({
        ...form,
        sequence: Number(form.sequence),
        planned_departure: iso(form.planned_departure),
        planned_arrival: iso(form.planned_arrival),
        actual_departure: null,
        actual_arrival: null,
        carrier: form.carrier || null,
        origin: form.origin || null,
        destination: form.destination || null,
        vessel: form.vessel || null,
        voyage: form.voyage || null,
        flight: form.flight || null,
        vehicle_reference: form.vehicle_reference || null,
      });
    },
    onSuccess: () => {
      setOpen(false);
      setForm({
        shipment_id: "",
        sequence: "1",
        mode: "Road",
        carrier: "",
        origin: "",
        destination: "",
        planned_departure: "",
        planned_arrival: "",
        vessel: "",
        voyage: "",
        flight: "",
        vehicle_reference: "",
      });
      client.invalidateQueries({ queryKey: ["transport"] });
    },
  });
  const rows = result.data?.items || [];
  return (
    <CloudflarePageShell className="cf-transport-page">
      <PageHeader
        icon={Truck}
        title="Transportasi"
        description="Tinjau leg pergerakan yang tersimpan untuk pengiriman tanpa menyiratkan pelacakan langsung."
        actions={
          <Button icon={Plus} onClick={() => setOpen(true)}>
            Tambah leg
          </Button>
        }
      />
      <FilterBar label="Cari transportasi">
        <SearchField
          value={query}
          onChange={setQuery}
          placeholder="Cari pengangkut, rute, atau referensi"
          ariaLabel="Cari transportasi"
        />
        <span className="cf-metadata">{rows.length} leg</span>
      </FilterBar>
      {result.isPending ? (
        <LoadingState label="Memuat transportasi…" className="page-loading" />
      ) : result.isError ? (
        <StateNotice
          title="Daftar transportasi tidak tersedia saat ini."
          tone="danger"
        >
          Coba lagi setelah koneksi layanan pulih.
        </StateNotice>
      ) : (
        <DataTableSurface
          title="Daftar pergerakan"
          description="Jadwal diambil dari leg transportasi yang direkam pada pengiriman."
        >
          {rows.length ? (
            <div className="table-scroll">
              <Table>
                <Table.Header sticky>
                  <Table.Row>
                    <Table.Head>Moda</Table.Head>
                    <Table.Head>Pengangkut</Table.Head>
                    <Table.Head>Rute</Table.Head>
                    <Table.Head>Referensi</Table.Head>
                    <Table.Head>Pengiriman</Table.Head>
                    <Table.Head>Jadwal tiba</Table.Head>
                    <Table.Head>Status</Table.Head>
                    <Table.Head>
                      <span className="sr-only">Aksi</span>
                    </Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {rows.map((row) => {
                    const state = row.actual_arrival
                      ? "COMPLETED"
                      : row.actual_departure
                        ? "IN_PROGRESS"
                        : row.planned_departure
                          ? "PLANNED"
                          : "REVIEW";
                    return (
                      <Table.Row key={String(row.id)}>
                        <Table.Cell>
                          <span className="table-cell-primary">
                            {operationalTextLabel(String(row.mode || "—"))}
                          </span>
                          <small>Leg {String(row.sequence || "—")}</small>
                        </Table.Cell>
                        <Table.Cell>{String(row.carrier || "—")}</Table.Cell>
                        <Table.Cell>
                          {String(row.origin || "—")} →{" "}
                          {String(row.destination || "—")}
                        </Table.Cell>
                        <Table.Cell>{reference(row)}</Table.Cell>
                        <Table.Cell>
                          {String(row.shipment_reference || "—")}
                        </Table.Cell>
                        <Table.Cell>
                          {date(row.planned_arrival || row.actual_arrival)}
                        </Table.Cell>
                        <Table.Cell>
                          <OperationalState value={state} />
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
                    );
                  })}
                </Table.Body>
              </Table>
            </div>
          ) : (
            <EmptyState
              icon={<Truck size={20} />}
              title="Belum ada leg transportasi"
              description="Leg transportasi akan tampil ketika direkam pada pengiriman."
            />
          )}
        </DataTableSurface>
      )}
      <DialogRoot open={open} onOpenChange={setOpen}>
        <Dialog className="cf-register-dialog cf-register-dialog--wide">
          <Dialog.Title>Tambah leg transportasi</Dialog.Title>
          <Dialog.Description>
            Jadwal ini adalah data operasional tersimpan, bukan tracking
            real-time.
          </Dialog.Description>
          <form
            className="dialog-form"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            <AppCombobox
              label="Pengiriman"
              required
              value={form.shipment_id}
              onValueChange={(shipment_id) => setForm({ ...form, shipment_id })}
              options={[
                {
                  value: "",
                  label: shipments.isPending
                    ? "Memuat pengiriman…"
                    : "Pilih pengiriman",
                },
                ...(shipments.data?.items || []).map((shipment) => ({
                  value: String(shipment.id),
                  label: `${shipment.internal_reference} · ${shipment.origin} → ${shipment.destination}`,
                })),
              ]}
            />
            <div className="form-grid">
              <Input
                label="Urutan leg"
                required
                type="number"
                min="1"
                value={form.sequence}
                onChange={(event) =>
                  setForm({ ...form, sequence: event.target.value })
                }
              />
              <AppSelect
                ariaLabel="Moda transportasi"
                label="Moda"
                value={form.mode}
                onValueChange={(mode) => setForm({ ...form, mode })}
                options={[
                  { value: "Road", label: "Darat" },
                  { value: "Sea", label: "Laut" },
                  { value: "Air", label: "Udara" },
                  { value: "Rail", label: "Rel" },
                ]}
              />
              <Input
                label="Pengangkut"
                value={form.carrier}
                onChange={(event) =>
                  setForm({ ...form, carrier: event.target.value })
                }
              />
              <Input
                label="Asal"
                value={form.origin}
                onChange={(event) =>
                  setForm({ ...form, origin: event.target.value })
                }
              />
              <Input
                label="Tujuan"
                value={form.destination}
                onChange={(event) =>
                  setForm({ ...form, destination: event.target.value })
                }
              />
              <Input
                label="Berangkat"
                type="datetime-local"
                value={form.planned_departure}
                onChange={(event) =>
                  setForm({ ...form, planned_departure: event.target.value })
                }
              />
              <Input
                label="Tiba"
                type="datetime-local"
                value={form.planned_arrival}
                onChange={(event) =>
                  setForm({ ...form, planned_arrival: event.target.value })
                }
              />
              <Input
                label="Referensi kendaraan / kapal"
                value={form.vehicle_reference}
                onChange={(event) =>
                  setForm({ ...form, vehicle_reference: event.target.value })
                }
              />
            </div>
            <div className="form-grid">
              <Input
                label="Kapal"
                value={form.vessel}
                onChange={(event) =>
                  setForm({ ...form, vessel: event.target.value })
                }
              />
              <Input
                label="Pelayaran"
                value={form.voyage}
                onChange={(event) =>
                  setForm({ ...form, voyage: event.target.value })
                }
              />
              <Input
                label="Penerbangan"
                value={form.flight}
                onChange={(event) =>
                  setForm({ ...form, flight: event.target.value })
                }
              />
            </div>
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
                disabled={mutation.isPending || !form.shipment_id}
              >
                {mutation.isPending ? "Menyimpan…" : "Simpan leg"}
              </Button>
            </div>
          </form>
        </Dialog>
      </DialogRoot>
    </CloudflarePageShell>
  );
}
