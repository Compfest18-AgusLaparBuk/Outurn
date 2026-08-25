"use client";

import { Dialog, DialogRoot } from "@cloudflare/kumo/components/dialog";
import { Input } from "@cloudflare/kumo/components/input";
import { Table } from "@cloudflare/kumo/components/table";
import { WarningCircleIcon as ShieldWarning } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ActionLink, Button } from "@/components/ui/button";
import {
  operationalTextLabel,
  OperationalState,
  StateNotice,
} from "@/components/ui/operational-primitives";
import { PageHeader } from "@/components/ui/page-header";
import { AppSelect } from "@/components/ui/select";
import {
  CloudflarePageShell,
  DataTableSurface,
  EmptyState,
  LoadingState,
} from "@/components/ui/page-primitives";
import {
  adjudicateScreening,
  fetchOperationsList,
  fetchWorkspaceContext,
} from "@/lib/api";

type Row = Record<string, unknown>;

function run(value: unknown) {
  return (value && typeof value === "object" ? value : {}) as Row;
}

function date(value: unknown) {
  return value ? new Date(String(value)).toLocaleString("id-ID") : "—";
}

export default function ScreeningPage() {
  const client = useQueryClient();
  const [selected, setSelected] = useState<Row | null>(null);
  const [disposition, setDisposition] = useState("REQUIRES_REVIEW");
  const [comment, setComment] = useState("");
  const context = useQuery({
    queryKey: ["workspace-context"],
    queryFn: fetchWorkspaceContext,
  });
  const result = useQuery({
    queryKey: ["screening"],
    queryFn: () => fetchOperationsList("/screening"),
  });
  const rows = useMemo(() => result.data?.items ?? [], [result.data?.items]);
  const notConfigured = rows.some((row) => {
    const item = run(row.run);
    return (
      String(item.provider) === "NOT_CONFIGURED" ||
      String(item.result) === "NOT_CONFIGURED"
    );
  });
  const canAdjudicate =
    context.data?.role === "admin" || context.data?.role === "supervisor";
  const adjudicate = useMutation({
    mutationFn: () =>
      adjudicateScreening(String(run(selected?.run).id), {
        disposition,
        comment,
      }),
    onSuccess: () => {
      setSelected(null);
      setComment("");
      setDisposition("REQUIRES_REVIEW");
      client.invalidateQueries({ queryKey: ["screening"] });
      client.invalidateQueries({ queryKey: ["assurance"] });
      client.invalidateQueries({ queryKey: ["workspace-shipment"] });
    },
  });

  return (
    <CloudflarePageShell className="cf-screening-page">
      <PageHeader
        icon={ShieldWarning}
        title="Screening pihak"
        description="Tinjau status penyedia dan hasil penyaringan yang tercatat untuk pihak terkait pada pengiriman."
      />
      {notConfigured && (
        <StateNotice
          tone="warning"
          title="Penyedia penyaringan belum dikonfigurasi"
        >
          Penyedia belum siap; hasil belum dapat dianggap Lulus.
        </StateNotice>
      )}
      {result.isPending ? (
        <LoadingState
          label="Memuat hasil penyaringan…"
          className="page-loading"
        />
      ) : result.isError ? (
        <StateNotice
          title="Hasil penyaringan tidak tersedia saat ini."
          tone="danger"
        >
          Coba lagi setelah koneksi layanan pulih.
        </StateNotice>
      ) : (
        <DataTableSurface
          title="Hasil penyaringan"
          description="Hasil, penyedia, dan waktu diambil langsung dari pemeriksaan yang tersimpan."
        >
          {rows.length ? (
            <div className="table-scroll">
              <Table>
                <Table.Header sticky>
                  <Table.Row>
                    <Table.Head>Entitas</Table.Head>
                    <Table.Head>Pengiriman</Table.Head>
                    <Table.Head>Hasil</Table.Head>
                    <Table.Head>Penyedia</Table.Head>
                    <Table.Head>Keputusan</Table.Head>
                    <Table.Head>Ditinjau</Table.Head>
                    <Table.Head>Skor</Table.Head>
                    <Table.Head>Waktu</Table.Head>
                    <Table.Head>
                      <span className="sr-only">Aksi</span>
                    </Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {rows.map((row) => {
                    const item = run(row.run);
                    const configured =
                      String(item.provider) !== "NOT_CONFIGURED";
                    const review = String(
                      item.disposition ||
                        (configured ? item.result || "REVIEW" : "REVIEW"),
                    );
                    return (
                      <Table.Row key={String(item.id || row.id)}>
                        <Table.Cell>
                          <span className="table-cell-primary">
                            {String(row.party || "—")}
                          </span>
                        </Table.Cell>
                        <Table.Cell>
                          {row.shipment_reference ? (
                            <ActionLink
                              href={`/shipments/${String(item.shipment_id)}`}
                              variant="ghost"
                            >
                              {String(row.shipment_reference)}
                            </ActionLink>
                          ) : (
                            "—"
                          )}
                        </Table.Cell>
                        <Table.Cell>
                          <OperationalState
                            value={String(item.result || "NOT_CONFIGURED")}
                          />
                        </Table.Cell>
                        <Table.Cell>
                          {operationalTextLabel(
                            String(item.provider || "NOT_CONFIGURED"),
                          )}
                        </Table.Cell>
                        <Table.Cell>
                          <OperationalState value={review} />
                        </Table.Cell>
                        <Table.Cell>
                          {item.reviewed_at
                            ? date(item.reviewed_at)
                            : "Belum direview"}
                        </Table.Cell>
                        <Table.Cell>
                          {item.score === null || item.score === undefined
                            ? "—"
                            : String(item.score)}
                        </Table.Cell>
                        <Table.Cell>{date(item.screened_at)}</Table.Cell>
                        <Table.Cell>
                          <div className="cf-rail-action-stack">
                            {canAdjudicate ? (
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => {
                                  setSelected(row);
                                  setDisposition(
                                    String(
                                      item.disposition || "REQUIRES_REVIEW",
                                    ),
                                  );
                                }}
                              >
                                Tinjau
                              </Button>
                            ) : null}
                            {item.shipment_id ? (
                              <ActionLink
                                href={`/shipments/${String(item.shipment_id)}`}
                                variant="ghost"
                              >
                                Buka
                              </ActionLink>
                            ) : null}
                          </div>
                        </Table.Cell>
                      </Table.Row>
                    );
                  })}
                </Table.Body>
              </Table>
            </div>
          ) : (
            <EmptyState
              icon={<ShieldWarning size={20} />}
              title="Belum ada pemeriksaan"
              description="Pemeriksaan akan tampil setelah dijalankan untuk pihak pada pengiriman."
            />
          )}
        </DataTableSurface>
      )}
      <DialogRoot
        open={Boolean(selected)}
        onOpenChange={(open) => {
          if (!open) {
            setSelected(null);
            setComment("");
          }
        }}
      >
        <Dialog className="cf-release-approval-dialog">
          <Dialog.Title>Keputusan penyaringan</Dialog.Title>
          <Dialog.Description>
            Keputusan peninjau tersimpan pada pemeriksaan dan jaminan. Penyedia
            yang belum tersedia tidak dapat ditandai Lulus.
          </Dialog.Description>
          <form
            className="dialog-form"
            onSubmit={(event) => {
              event.preventDefault();
              adjudicate.mutate();
            }}
          >
            <AppSelect
              ariaLabel="Keputusan penyaringan"
              value={disposition}
              onValueChange={setDisposition}
              options={[
                { value: "REQUIRES_REVIEW", label: "Tetap perlu ditinjau" },
                { value: "CLEAR", label: "Lulus" },
                { value: "MATCH", label: "Konfirmasi kecocokan" },
                { value: "FALSE_POSITIVE", label: "Bukan kecocokan" },
              ]}
            />
            <Input
              label="Alasan peninjauan"
              value={comment}
              minLength={2}
              onChange={(event) => setComment(event.target.value)}
              description="Minimal 2 karakter untuk audit."
            />
            {adjudicate.isError ? (
              <p role="alert" className="form-error">
                {(adjudicate.error as Error).message}
              </p>
            ) : null}
            <div className="form-panel__actions">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setSelected(null)}
              >
                Batal
              </Button>
              <Button
                type="submit"
                disabled={adjudicate.isPending || comment.trim().length < 2}
              >
                {adjudicate.isPending ? "Menyimpan…" : "Simpan keputusan"}
              </Button>
            </div>
          </form>
        </Dialog>
      </DialogRoot>
    </CloudflarePageShell>
  );
}
