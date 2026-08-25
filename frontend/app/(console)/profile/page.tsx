"use client";

import {
  ActivityIcon as Activity,
  UserListIcon as UserList,
} from "@phosphor-icons/react";
import { ActionLink } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import {
  CloudflarePageShell,
  DataTableSurface,
} from "@/components/ui/page-primitives";

export default function ProfilePage() {
  return (
    <CloudflarePageShell className="profile-page">
      <PageHeader
        icon={UserList}
        title="Profil saya"
        description="Preferensi ruang kerja dan pintasan pengaturan Anda."
      />
      <DataTableSurface className="profile-card">
        <div className="profile-card__identity">
          <span className="profile-card__avatar">O</span>
          <div>
            <h2>Operator Outurn</h2>
            <p>Ruang kerja lokal tanpa login</p>
            <span className="profile-card__role">Operator</span>
          </div>
        </div>
        <dl className="profile-card__facts">
          <div>
            <dt>Status akses</dt>
            <dd>Aktif</dd>
          </div>
          <div>
            <dt>Ruang kerja</dt>
            <dd>Outurn Operations</dd>
          </div>
          <div>
            <dt>Mode akses</dt>
            <dd>Langsung ke sistem</dd>
          </div>
        </dl>
        <div className="profile-card__actions">
          <ActionLink
            href="/settings/notifications"
            icon={Activity}
            variant="secondary"
          >
            Atur notifikasi
          </ActionLink>
        </div>
      </DataTableSurface>
    </CloudflarePageShell>
  );
}
