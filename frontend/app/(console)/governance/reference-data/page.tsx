"use client";

import { Dialog } from "@cloudflare/kumo/components/dialog";
import { Input } from "@cloudflare/kumo/components/input";
import { Table } from "@cloudflare/kumo/components/table";
import {
  PlusIcon as Plus,
  ArchiveIcon as ReferenceIcon,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DataTableSurface,
  EmptyState,
  FilterBar,
  LoadingState,
  SearchField,
} from "@/components/ui/page-primitives";
import {
  OperationalState,
  operationalTextLabel,
  StateNotice,
} from "@/components/ui/operational-primitives";
import { PageHeader } from "@/components/ui/page-header";
import { AppSelect } from "@/components/ui/select";
import { createReferenceData, fetchReferenceData } from "@/lib/api";

type ReferenceItem = {
  id: string;
  category: string;
  code: string;
  label: string;
  source: string;
  version: string;
  active: boolean;
};

export default function ReferenceDataPage() {
  const client = useQueryClient();
  const result = useQuery({
    queryKey: ["reference-data"],
    queryFn: () => fetchReferenceData(),
  });
  const [form, setForm] = useState({
    category: "COUNTRY",
    code: "",
    label: "",
    source: "Workspace maintained",
    version: "1",
  });
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const mutation = useMutation({
    mutationFn: () => createReferenceData(form),
    onSuccess: () => {
      setOpen(false);
      setForm({
        category: "COUNTRY",
        code: "",
        label: "",
        source: "Workspace maintained",
        version: "1",
      });
      client.invalidateQueries({ queryKey: ["reference-data"] });
    },
  });
  const items = useMemo(
    () => (result.data?.items || []) as ReferenceItem[],
    [result.data],
  );
  const categories = useMemo(
    () => [
      { value: "", label: "Semua kategori" },
      ...Array.from(new Set(items.map((item) => item.category)))
        .sort()
        .map((value) => ({ value, label: value })),
    ],
    [items],
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter(
      (item) =>
        (!category || item.category === category) &&
        (!needle ||
          [
            item.category,
            item.code,
            item.label,
            item.source,
            item.version,
          ].some((value) => value.toLowerCase().includes(needle))),
    );
  }, [category, items, query]);
  return (
    <div className="operations-page cf-reference-data-page">
      <PageHeader
        icon={ReferenceIcon}
        title="Data referensi"
        description="Kode dan label referensi yang dipakai ruang kerja agar kolom operasional konsisten dan memiliki sumber yang jelas."
        actions={
          <Button icon={Plus} onClick={() => setOpen(true)}>
            Tambah entri
          </Button>
        }
      />
      <StateNotice title="Data referensi mengikuti ruang kerja" tone="info">
        Sumber dan versi disimpan bersama entri.
      </StateNotice>
      <FilterBar className="cf-reference-toolbar" label="Filter data referensi">
        <SearchField
          value={query}
          onChange={setQuery}
          placeholder="Cari kategori, kode, label, atau sumber"
          ariaLabel="Cari data referensi"
        />
        <AppSelect
          ariaLabel="Filter kategori data referensi"
          value={category}
          onValueChange={setCategory}
          options={categories}
        />
      </FilterBar>
      <DataTableSurface
        title="Entri data referensi"
        description={`${filtered.length} dari ${items.length} entri. Sumber dan versi selalu ditampilkan untuk peninjau.`}
      >
        {result.isLoading ? (
          <LoadingState label="Memuat data referensi…" />
        ) : result.error ? (
          <EmptyState
            icon={<ReferenceIcon size={18} />}
            title="Data referensi tidak dapat dimuat"
            description={
              result.error instanceof Error
                ? result.error.message
                : "Coba muat ulang data referensi."
            }
          />
        ) : !filtered.length ? (
          <EmptyState
            icon={<ReferenceIcon size={18} />}
            title="Tidak ada entri yang cocok"
            description="Ubah kata kunci atau filter kategori untuk mencari nilai lain."
          />
        ) : (
          <div className="table-scroll">
            <Table>
              <Table.Header sticky>
                <Table.Row>
                  <Table.Head>Kategori</Table.Head>
                  <Table.Head>Kode</Table.Head>
                  <Table.Head>Label</Table.Head>
                  <Table.Head>Sumber</Table.Head>
                  <Table.Head>Versi</Table.Head>
                  <Table.Head>Status</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {filtered.map((item) => (
                  <Table.Row key={item.id}>
                    <Table.Cell>
                      <span className="table-cell-primary">
                        {item.category}
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="mono">{item.code}</span>
                    </Table.Cell>
                    <Table.Cell>{item.label}</Table.Cell>
                    <Table.Cell>{operationalTextLabel(item.source)}</Table.Cell>
                    <Table.Cell>
                      <span className="mono">{item.version}</span>
                    </Table.Cell>
                    <Table.Cell>
                      <OperationalState
                        value={item.active ? "ACTIVE" : "INACTIVE"}
                      />
                    </Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </div>
        )}
      </DataTableSurface>
      {open ? (
        <Dialog.Root open onOpenChange={(next) => setOpen(next)}>
          <Dialog className="cf-reference-dialog" size="base">
            <Dialog.Title>Tambah reference entry</Dialog.Title>
            <Dialog.Description>
              Gunakan code stabil, source yang dapat diverifikasi, dan version
              yang dapat direview.
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
                  label="Kategori"
                  required
                  value={form.category}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      category: event.target.value.toUpperCase(),
                    })
                  }
                />
                <Input
                  label="Code"
                  required
                  value={form.code}
                  onChange={(event) =>
                    setForm({ ...form, code: event.target.value.toUpperCase() })
                  }
                />
                <Input
                  label="Label"
                  required
                  value={form.label}
                  onChange={(event) =>
                    setForm({ ...form, label: event.target.value })
                  }
                />
                <Input
                  label="Source"
                  required
                  value={form.source}
                  onChange={(event) =>
                    setForm({ ...form, source: event.target.value })
                  }
                />
                <Input
                  label="Version"
                  required
                  value={form.version}
                  onChange={(event) =>
                    setForm({ ...form, version: event.target.value })
                  }
                />
              </div>
              {mutation.isError ? (
                <p className="form-error" role="alert">
                  {(mutation.error as Error).message}
                </p>
              ) : null}
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
                  variant="primary"
                  disabled={mutation.isPending}
                >
                  {mutation.isPending ? "Menyimpan…" : "Simpan entri"}
                </Button>
              </div>
            </form>
          </Dialog>
        </Dialog.Root>
      ) : null}
    </div>
  );
}
