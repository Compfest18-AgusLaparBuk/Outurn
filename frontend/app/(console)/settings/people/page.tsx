"use client";

import { Dialog, DialogRoot } from "@cloudflare/kumo/components/dialog";
import { Table } from "@cloudflare/kumo/components/table";
import {
  PlusIcon as Plus,
  UsersThreeIcon as UsersThree,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { LoadingState } from "@/components/ui/page-primitives";
import { StateNotice } from "@/components/ui/operational-primitives";
import { AppSelect } from "@/components/ui/select";
import { Input } from "@cloudflare/kumo/components/input";
import {
  createUser,
  fetchUsers,
  fetchWorkspaceContext,
  updateUser,
} from "@/lib/api";
import { useSettingsCopy } from "@/components/settings/settings-copy";

export default function PeoplePage() {
  const { language, t } = useSettingsCopy();
  const client = useQueryClient();
  const context = useQuery({
    queryKey: ["workspace-context"],
    queryFn: fetchWorkspaceContext,
    retry: false,
  });
  const canManagePeople = context.data?.role === "admin";
  const result = useQuery({
    queryKey: ["users"],
    queryFn: fetchUsers,
    enabled: canManagePeople,
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    display_name: "",
    email: "",
    password: "",
    role: "operator",
  });
  const mutation = useMutation({
    mutationFn: () => createUser(form),
    onSuccess: () => {
      setOpen(false);
      setForm({ display_name: "", email: "", password: "", role: "operator" });
      client.invalidateQueries({ queryKey: ["users"] });
    },
  });
  const statusMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      updateUser(id, { active }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["users"] }),
  });

  if (context.isPending)
    return (
      <main className="grid min-h-screen place-items-center text-sm text-[var(--subtle)]">
        <LoadingState label="Memuat sesi Outurn…" />
      </main>
    );
  if (!canManagePeople)
    return (
      <StateNotice title={t.administratorsOnly} tone="danger">
        Hubungi administrator workspace untuk melanjutkan.
      </StateNotice>
    );

  const users = result.data || [];
  const active = users.filter((item) => item.active);
  const operators = users.filter((item) => item.role === "operator");
  const reviewers = users.filter((item) => item.role === "supervisor");
  const admins = users.filter((item) => item.role === "admin");

  return (
    <div className="operations-page">
      <PageHeader
        icon={UsersThree}
        title={t.peopleAndAccess}
        description={t.peoplePageDescription}
        actions={
          <Button icon={Plus} onClick={() => setOpen(true)}>
            {t.addPerson}
          </Button>
        }
      />
      <section
        className="metric-grid metric-grid--four"
        aria-label={t.peopleAndAccess}
      >
        <div className="metric-cell">
          <span>{t.activeUsers}</span>
          <strong>{active.length}</strong>
          <small>{t.canSignInNow}</small>
        </div>
        <div className="metric-cell">
          <span>{t.operators}</span>
          <strong>{operators.length}</strong>
          <small>{t.prepareShipmentWork}</small>
        </div>
        <div className="metric-cell">
          <span>{t.reviewers}</span>
          <strong>{reviewers.length}</strong>
          <small>{t.reviewAndDecide}</small>
        </div>
        <div className="metric-cell">
          <span>{t.administrators}</span>
          <strong>{admins.length}</strong>
          <small>{t.manageWorkspaceAccess}</small>
        </div>
      </section>
      <section
        className="data-panel data-panel--wide"
        aria-labelledby="workspace-people-title"
      >
        <div className="data-panel__header">
          <div>
            <h2 id="workspace-people-title">{t.workspacePeople}</h2>
            <p>{t.accessChangesLogged}</p>
          </div>
        </div>
        <div className="table-scroll">
          <Table>
            <Table.Header sticky>
              <Table.Row>
                <Table.Head>{t.person}</Table.Head>
                <Table.Head>{t.role}</Table.Head>
                <Table.Head>{t.status}</Table.Head>
                <Table.Head>{t.lastLogin}</Table.Head>
                <Table.Head>{t.action}</Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {users.map((item) => (
                <Table.Row key={item.id}>
                  <Table.Cell>
                    <span className="table-cell-primary">
                      {item.display_name}
                    </span>
                    <small>{item.email}</small>
                  </Table.Cell>
                  <Table.Cell>
                    {item.role === "supervisor"
                      ? "Peninjau"
                      : item.role === "admin"
                        ? "Administrator"
                        : "Operator"}
                  </Table.Cell>
                  <Table.Cell>{item.active ? t.active : t.disabled}</Table.Cell>
                  <Table.Cell>
                    {item.last_login_at
                      ? new Date(item.last_login_at).toLocaleString(
                          language === "id" ? "id-ID" : "en-GB",
                        )
                      : t.never}
                  </Table.Cell>
                  <Table.Cell>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={
                        statusMutation.isPending ||
                        (item.role === "admin" && admins.length === 1)
                      }
                      onClick={() =>
                        statusMutation.mutate({
                          id: item.id,
                          active: !item.active,
                        })
                      }
                    >
                      {statusMutation.isPending
                        ? "Menyimpan…"
                        : item.active
                          ? t.deactivate
                          : t.reactivate}
                    </Button>
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        </div>
        {!users.length && (
          <div className="empty-state">
            <span className="empty-state__title">{t.noPeopleYet}</span>
            <span>{t.addOperatorReviewer}</span>
          </div>
        )}
      </section>
      {statusMutation.isError ? (
        <p className="form-error" role="alert">
          Perubahan status pengguna gagal.{" "}
          {(statusMutation.error as Error).message}
        </p>
      ) : null}
      <DialogRoot open={open} onOpenChange={setOpen}>
        <Dialog className="person-dialog">
          <Dialog.Title>{t.addPersonTitle}</Dialog.Title>
          <Dialog.Description>{t.addPersonDescription}</Dialog.Description>
          <form
            className="dialog-form"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            <Input
              label={t.displayName}
              required
              value={form.display_name}
              onChange={(event) =>
                setForm({ ...form, display_name: event.target.value })
              }
            />
            <Input
              label="Email"
              required
              type="email"
              autoComplete="email"
              value={form.email}
              onChange={(event) =>
                setForm({ ...form, email: event.target.value })
              }
            />
            <Input
              label={t.temporaryPassword}
              required
              minLength={12}
              type="password"
              autoComplete="new-password"
              description={t.temporaryPasswordHint}
              value={form.password}
              onChange={(event) =>
                setForm({ ...form, password: event.target.value })
              }
            />
            <AppSelect
              ariaLabel={t.role}
              label={t.role}
              value={form.role}
              onValueChange={(role) => setForm({ ...form, role })}
              options={[
                { value: "operator", label: "Operator" },
                { value: "supervisor", label: "Peninjau" },
              ]}
            />
            {mutation.isError && (
              <p role="alert" className="form-error">
                {(mutation.error as Error).message}
              </p>
            )}
            <div className="form-panel__actions">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setOpen(false)}
              >
                {t.cancel}
              </Button>
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? t.adding : t.addPerson}
              </Button>
            </div>
          </form>
        </Dialog>
      </DialogRoot>
    </div>
  );
}
