"use client";

import {
  ArrowLeftIcon as ArrowLeft,
  PackageIcon as Package,
} from "@phosphor-icons/react";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { ChangeEvent } from "react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { CloudflarePageShell } from "@/components/ui/page-primitives";
import { AppSelect } from "@/components/ui/select";
import { Input } from "@cloudflare/kumo/components/input";
import { createShipment } from "@/lib/api";

export default function NewShipmentPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    internal_reference: "",
    external_reference: "",
    origin: "",
    destination: "",
    transport_mode: "Road",
    expected_recipient: "",
    expected_currency: "",
    expected_total: "",
  });
  const mutation = useMutation({
    mutationFn: () =>
      createShipment({
        ...form,
        expected_total: form.expected_total
          ? Number(form.expected_total)
          : null,
      }),
    onSuccess: (shipment) => router.push(`/shipments/${shipment.id}`),
  });
  const update =
    (field: keyof typeof form) => (event: ChangeEvent<HTMLInputElement>) =>
      setForm((current) => ({ ...current, [field]: event.target.value }));
  return (
    <CloudflarePageShell className="cf-shipment-create-page">
      <Link className="back-link" href="/shipments">
        <ArrowLeft size={15} /> Kembali ke pengiriman
      </Link>
      <PageHeader
        icon={Package}
        title="Buat pengiriman"
        description="Mulai satu kasus sebelum dokumen tiba agar setiap pemeriksaan dan keputusan tetap terhubung."
      />
      <form
        className="form-panel"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <div className="form-panel__heading">
          <div>
            <h2>Detail pengiriman</h2>
            <p>Gunakan referensi yang mudah dikenali tim saat serah terima.</p>
          </div>
        </div>
        <div className="form-grid">
          <Input
            label="Referensi pengiriman"
            required
            value={form.internal_reference}
            onChange={update("internal_reference")}
            placeholder="mis. SHP-2026-001"
          />
          <Input
            label="Referensi pesanan"
            description="Opsional"
            value={form.external_reference}
            onChange={update("external_reference")}
            placeholder="mis. PO-4821"
          />
          <Input
            label="Asal"
            required
            value={form.origin}
            onChange={update("origin")}
            placeholder="Gudang atau kota"
          />
          <Input
            label="Tujuan"
            required
            value={form.destination}
            onChange={update("destination")}
            placeholder="Pelanggan atau lokasi pengiriman"
          />
          <AppSelect
            ariaLabel="Moda transportasi"
            label="Moda transportasi"
            value={form.transport_mode}
            onValueChange={(transport_mode) =>
              setForm((current) => ({ ...current, transport_mode }))
            }
            options={[
              { value: "Road", label: "Darat" },
              { value: "Sea", label: "Laut" },
              { value: "Air", label: "Udara" },
              { value: "Rail", label: "Rel" },
            ]}
          />
          <Input
            label="Penerima yang diharapkan"
            description="Opsional"
            value={form.expected_recipient}
            onChange={update("expected_recipient")}
            placeholder="Nama pada surat jalan"
          />
          <Input
            label="Mata uang"
            description="Opsional"
            value={form.expected_currency}
            onChange={update("expected_currency")}
            placeholder="IDR"
            maxLength={8}
          />
          <Input
            label="Total yang diharapkan"
            description="Opsional"
            type="number"
            min="0"
            value={form.expected_total}
            onChange={update("expected_total")}
            placeholder="0"
          />
        </div>
        {mutation.isError && (
          <p role="alert" className="form-error">
            {(mutation.error as Error).message}
          </p>
        )}
        <div className="form-panel__actions">
          <Button
            type="button"
            variant="secondary"
            onClick={() => router.back()}
          >
            Batal
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Membuat…" : "Buat pengiriman"}
          </Button>
        </div>
      </form>
    </CloudflarePageShell>
  );
}
