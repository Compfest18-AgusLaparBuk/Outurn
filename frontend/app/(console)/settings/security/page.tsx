"use client";

import { PageHeader } from "@/components/ui/page-header";

export default function SecuritySettingsPage() {
  return (
    <div className="operations-page">
      <PageHeader
        title="Keamanan"
        description="Status proteksi data dan catatan operasional pada ruang kerja ini."
      />
      <div className="dashboard-grid">
        <section className="data-panel" aria-labelledby="security-data-title">
          <h2 id="security-data-title">Proteksi data</h2>
          <dl className="definition-list">
            <div><dt>Penyimpanan</dt><dd>Dokumen tersimpan di vault terstruktur per ruang kerja</dd></div>
            <div><dt>Koneksi integrasi</dt><dd>Kredensial disimpan terenkripsi dan tidak pernah ditampilkan</dd></div>
            <div><dt>Akses aplikasi</dt><dd>Tanpa login — semua pengguna perangkat ini langsung masuk ke sistem</dd></div>
          </dl>
        </section>
        <section className="data-panel" aria-labelledby="security-audit-title">
          <h2 id="security-audit-title">Jejak audit</h2>
          <dl className="definition-list">
            <div><dt>Peristiwa operasional</dt><dd>Rekonsiliasi, pengecualian, dan keputusan pelepasan tercatat</dd></div>
            <div><dt>Log aktivitas</dt><dd>Semua perubahan tercatat pada halaman Log aktivitas</dd></div>
            <div><dt>Retensi</dt><dd>Diatur melalui pengaturan retensi ruang kerja</dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}
