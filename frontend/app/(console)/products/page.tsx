"use client";

import { Checkbox } from "@cloudflare/kumo/components/checkbox";
import { Dialog, DialogRoot } from "@cloudflare/kumo/components/dialog";
import { Input } from "@cloudflare/kumo/components/input";
import { Table } from "@cloudflare/kumo/components/table";
import { PackageIcon as Cube, PlusIcon as Plus } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useDeferredValue, useState } from "react";
import { ActionLink, Button } from "@/components/ui/button";
import {
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
import { createProduct, fetchOperationsList, fetchShipments } from "@/lib/api";

export default function ProductsPage() {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    shipment_id: "",
    line_number: "1",
    sku: "",
    description: "",
    quantity: "1",
    unit_of_measure: "unit",
    hs_code: "",
    country_of_origin: "ID",
    dangerous_goods: false,
    un_number: "",
    proper_shipping_name: "",
    hazard_class: "",
    packing_group: "",
    special_handling: "",
    package_count: "",
  });
  const deferredQuery = useDeferredValue(query);
  const result = useQuery({
    queryKey: ["products", deferredQuery],
    queryFn: () =>
      fetchOperationsList(
        "/products",
        deferredQuery ? { q: deferredQuery } : undefined,
      ),
  });
  const shipments = useQuery({
    queryKey: ["shipments", "product-create"],
    queryFn: () => fetchShipments(new URLSearchParams("page_size=100")),
    enabled: open,
  });
  const mutation = useMutation({
    mutationFn: () => {
      if (!form.shipment_id)
        throw new Error("Pilih pengiriman terlebih dahulu.");
      return createProduct({
        ...form,
        line_number: Number(form.line_number),
        quantity: Number(form.quantity),
        package_count: form.package_count ? Number(form.package_count) : null,
        unit_price: null,
        currency: null,
        line_total: null,
        hs_code: form.hs_code || null,
        country_of_origin: form.country_of_origin || null,
        un_number: form.dangerous_goods ? form.un_number || null : null,
        proper_shipping_name: form.dangerous_goods
          ? form.proper_shipping_name || null
          : null,
        hazard_class: form.dangerous_goods ? form.hazard_class || null : null,
        packing_group: form.dangerous_goods ? form.packing_group || null : null,
        special_handling: form.special_handling || null,
      });
    },
    onSuccess: () => {
      setOpen(false);
      setForm({
        shipment_id: "",
        line_number: "1",
        sku: "",
        description: "",
        quantity: "1",
        unit_of_measure: "unit",
        hs_code: "",
        country_of_origin: "ID",
        dangerous_goods: false,
        un_number: "",
        proper_shipping_name: "",
        hazard_class: "",
        packing_group: "",
        special_handling: "",
        package_count: "",
      });
      client.invalidateQueries({ queryKey: ["products"] });
    },
  });
  const rows = result.data?.items || [];
  return (
    <CloudflarePageShell className="cf-products-page">
      <PageHeader
        icon={Cube}
        title="Produk dan komoditas"
        description="Tinjau barang yang tercatat dalam pengiriman, termasuk klasifikasi dan kaitannya dengan barang berbahaya."
        actions={
          <Button icon={Plus} onClick={() => setOpen(true)}>
            Tambah komoditas
          </Button>
        }
      />
      <FilterBar label="Cari produk">
        <SearchField
          value={query}
          onChange={setQuery}
          placeholder="Cari SKU, deskripsi, atau kode HS"
          ariaLabel="Cari produk"
        />
        <span className="cf-metadata">{rows.length} komoditas</span>
      </FilterBar>
      {result.isPending ? (
        <LoadingState label="Memuat komoditas…" className="page-loading" />
      ) : result.isError ? (
        <StateNotice
          title="Daftar komoditas tidak tersedia saat ini."
          tone="danger"
        >
          Coba lagi setelah koneksi layanan pulih.
        </StateNotice>
      ) : (
        <DataTableSurface
          title="Daftar komoditas"
          description="Nilai di bawah ini berasal dari item pengiriman yang tersimpan."
        >
          {rows.length ? (
            <div className="table-scroll">
              <Table>
                <Table.Header sticky>
                  <Table.Row>
                    <Table.Head>Produk</Table.Head>
                    <Table.Head>Klasifikasi</Table.Head>
                    <Table.Head>Deskripsi</Table.Head>
                    <Table.Head>Barang berbahaya</Table.Head>
                    <Table.Head>Pengiriman</Table.Head>
                    <Table.Head>Review</Table.Head>
                    <Table.Head>
                      <span className="sr-only">Aksi</span>
                    </Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {rows.map((row) => {
                    const dangerous = Boolean(row.dangerous_goods);
                    return (
                      <Table.Row key={String(row.id)}>
                        <Table.Cell>
                          <span className="table-cell-primary">
                            {String(row.sku || "Tanpa SKU")}
                          </span>
                          <small>
                            {String(row.quantity || "—")}{" "}
                            {String(row.unit_of_measure || "")}
                          </small>
                        </Table.Cell>
                        <Table.Cell>{String(row.hs_code || "—")}</Table.Cell>
                        <Table.Cell>
                          {String(row.description || "—")}
                        </Table.Cell>
                        <Table.Cell>
                          {dangerous ? (
                            <OperationalState value="REVIEW" />
                          ) : (
                            <span className="cf-metadata">Tidak ditandai</span>
                          )}
                        </Table.Cell>
                        <Table.Cell>
                          {String(row.shipment_reference || "—")}
                        </Table.Cell>
                        <Table.Cell>
                          <OperationalState
                            value={
                              dangerous &&
                              (!row.un_number ||
                                !row.proper_shipping_name ||
                                !row.hazard_class)
                                ? "REVIEW"
                                : "CLEAR"
                            }
                          />
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
              icon={<Cube size={20} />}
              title="Belum ada komoditas"
              description="Komoditas akan tampil setelah dicatat pada pengiriman."
            />
          )}
        </DataTableSurface>
      )}
      <DialogRoot open={open} onOpenChange={setOpen}>
        <Dialog className="cf-register-dialog cf-register-dialog--wide">
          <Dialog.Title>Tambah komoditas</Dialog.Title>
          <Dialog.Description>
            Tambahkan item ke pengiriman yang sudah ada. Field dangerous goods
            akan ikut menjadi blocker jika belum lengkap.
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
                label="Nomor baris"
                required
                type="number"
                min="1"
                value={form.line_number}
                onChange={(event) =>
                  setForm({ ...form, line_number: event.target.value })
                }
              />
              <Input
                label="SKU"
                description="Opsional"
                value={form.sku}
                onChange={(event) =>
                  setForm({ ...form, sku: event.target.value })
                }
              />
              <Input
                label="Deskripsi"
                required
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
              <Input
                label="Jumlah"
                required
                type="number"
                min="0"
                step="any"
                value={form.quantity}
                onChange={(event) =>
                  setForm({ ...form, quantity: event.target.value })
                }
              />
              <Input
                label="Satuan"
                required
                value={form.unit_of_measure}
                onChange={(event) =>
                  setForm({ ...form, unit_of_measure: event.target.value })
                }
              />
              <Input
                label="HS code"
                description="Opsional"
                value={form.hs_code}
                onChange={(event) =>
                  setForm({ ...form, hs_code: event.target.value })
                }
              />
              <Input
                label="Negara asal"
                description="Opsional"
                maxLength={2}
                value={form.country_of_origin}
                onChange={(event) =>
                  setForm({
                    ...form,
                    country_of_origin: event.target.value.toUpperCase(),
                  })
                }
              />
              <Input
                label="Jumlah paket"
                description="Opsional"
                type="number"
                min="0"
                value={form.package_count}
                onChange={(event) =>
                  setForm({ ...form, package_count: event.target.value })
                }
              />
            </div>
            <Checkbox
              label="Tandai sebagai barang berbahaya"
              checked={form.dangerous_goods}
              onCheckedChange={(checked) =>
                setForm({ ...form, dangerous_goods: Boolean(checked) })
              }
            />
            {form.dangerous_goods && (
              <div className="form-grid">
                <Input
                  label="Nomor UN"
                  required
                  value={form.un_number}
                  onChange={(event) =>
                    setForm({ ...form, un_number: event.target.value })
                  }
                />
                <Input
                  label="Nama pengiriman"
                  required
                  value={form.proper_shipping_name}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      proper_shipping_name: event.target.value,
                    })
                  }
                />
                <Input
                  label="Kelas bahaya"
                  required
                  value={form.hazard_class}
                  onChange={(event) =>
                    setForm({ ...form, hazard_class: event.target.value })
                  }
                />
                <Input
                  label="Kelompok kemasan"
                  description="Opsional"
                  value={form.packing_group}
                  onChange={(event) =>
                    setForm({ ...form, packing_group: event.target.value })
                  }
                />
              </div>
            )}
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
                  mutation.isPending ||
                  !form.shipment_id ||
                  form.description.trim().length < 1
                }
              >
                {mutation.isPending ? "Menyimpan…" : "Simpan komoditas"}
              </Button>
            </div>
          </form>
        </Dialog>
      </DialogRoot>
    </CloudflarePageShell>
  );
}
