# GateGuard - Deep Gap & Security Review

Tanggal audit: 25 Agustus 2026
Baseline: `57eda11cf14e3ef75bff342a0921d47e4d7468f5` (`origin/main` setelah pull terbaru)

## Batas sumber dan interpretasi requirement

- `[AIC] AI Innovation Challenge.pdf` adalah rulebook kompetisi 28 halaman. Isinya mencakup tema AI for the Backbone of the Economy, tim 3-5 WNI, karya orisinal, izin memakai API/pre-trained model dengan fine-tuning sesuai inovasi, berkas pendaftaran, serta jadwal penyisihan. Ini menjadi batas kepatuhan untuk subset MVP AIC.
- `Pedoman Cloudflare.docx` adalah referensi visual berbasis screenshot (18 gambar). Isinya dipakai sebagai target layout, spacing, komponen, chart, state, dan UX; bukan pengganti acceptance criteria AIC.
- Instruksi pengguna meminta full app dibangun terlebih dahulu, baru dipilih subset yang masuk penyisihan AIC, serta meminta repo terbaru dari GitHub dipakai. Instruksi ini menjadi scope implementasi saat ini.

## Ringkasan eksekutif

Tidak ditemukan bukti langsung RCE, SQL injection, stored XSS sink, token di `localStorage`, atau dependency vulnerability HIGH/CRITICAL pada audit lokal. Fondasi auth, RBAC workspace, upload signature check, security headers, dan audit trail sudah cukup baik.

Namun ada satu blocker rilis dan enam gap penting:

1. **P0 release blocker - deployment live belum sinkron dengan commit terbaru.** Local source memiliki `/notifications`, `/healthz`, `/readyz`, dan `/api/health/ready`; host live mengembalikan 404 untuk semuanya. `/api/auth/me` dan `/api/ops/organizations` mengembalikan 401 JSON, sehingga host memang terhubung ke aplikasi/BFF, tetapi bukan build terbaru.
2. **High - request JSON belum dibatasi dan beberapa payload menerima `dict[str, Any]` tanpa schema ketat.** Ini membuka risiko memory/CPU amplification, data bloat, dan key setting arbitrer.
3. **Medium - proteksi CSRF bergantung pada header `Origin` jika header itu ada.** Request mutation tanpa `Origin` lolos; SameSite=Lax mengurangi risiko browser biasa, tetapi bukan defense-in-depth yang lengkap.
4. **Medium - CSP production masih mengizinkan `unsafe-inline`.** XSS menjadi lebih mudah dieksploitasi jika ada injection baru di masa depan.
5. **Medium - rate limit berada di memory proses.** Restart atau replica kedua membuat batas dapat dilewati.
6. **Medium - belum ada Host allowlist di FastAPI.** Saat ini mengandalkan Caddy/ingress; bila origin terekspos atau routing salah, host confusion/cache poisoning lebih sulit dicegah.
7. **Medium - validasi DNS webhook dan koneksi HTTP tidak atomic.** Worker memeriksa alamat publik lalu `httpx` melakukan resolusi ulang; DNS rebinding masih merupakan residual SSRF risk.

## Temuan terprioritas

### GG-OPS-001 - Live deployment drift (P0 release blocker)

- **Lokasi:** `backend/app/main.py:75-90`, `frontend/app/healthz/route.ts`, `frontend/app/readyz/route.ts`, `frontend/app/api/health/ready/route.ts`, `frontend/app/(console)/notifications/page.tsx`.
- **Evidence:** verifikasi 25-08-2026 ke `https://48.193.45.40.sslip.io`: `/login` = 200; `/api/auth/me` = 401 `UNAUTHENTICATED`; `/api/ops/organizations` = 401; `/healthz`, `/readyz`, `/api/health/ready`, `/notifications` = 404; `/settings/notifications` dan `/analytics` = 200.
- **Impact:** Demo/QA bisa memakai fitur dan route yang tidak ada di production. Readiness monitor juga tidak memeriksa kontrak yang sama dengan source terbaru.
- **Fix:** jalankan pipeline image SHA terbaru, lalu verifikasi `origin/main` SHA pada VM, container image digests, `/login`, `/healthz`, `/readyz`, `/api/health/ready`, dan `/notifications`. Tambahkan endpoint build metadata yang tidak membocorkan secret agar drift bisa dibuktikan otomatis.
- **Mitigasi sekarang:** jangan menyatakan URL live sudah memakai commit terbaru; jangan demo route baru sebelum smoke test remote lulus.
- **False-positive note:** status 401 bukan kegagalan konektivitas; justru membuktikan BFF/auth backend reachable. Masalahnya adalah freshness/route parity.

### GG-SEC-001 - Unbounded JSON payload dan settings mass assignment

- **Severity:** High.
- **Lokasi:** `backend/app/api/operations.py:90-92` (`SettingsPayload.values`), `backend/app/api/operations.py:1372-1393` (`inbound_shipment`), `frontend/app/api/ops/[...path]/route.ts:5-19`.
- **Evidence:** settings dan partner shipment menerima object arbitrer; BFF membaca body JSON/multipart tanpa batas umum. `save_settings` di `backend/app/repositories/operations.py:2539-2579` menyimpan setiap key yang tidak dikenal sebagai workspace setting.
- **Impact:** attacker yang sudah memiliki role/API token dapat mengirim object sangat besar/deeply nested, memenuhi memory/DB, membuat audit key list besar, atau menambah setting tak dikenal yang tidak pernah diuji UI.
- **Fix:** gunakan Pydantic model eksplisit dengan `extra="forbid"`, batas jumlah key, kedalaman, panjang string/list, dan schema shipment partner; allowlist key workspace (`name`, timezone, locale, currency, review policy, retention). Tambahkan request body limit di BFF, FastAPI/ASGI middleware, dan Caddy.
- **Mitigasi:** ingress limit minimal 32 MB untuk multipart dan limit jauh lebih kecil untuk JSON; shared WAF limit sebelum scale-out.
- **False-positive note:** tenant/RBAC tetap berjalan; temuan ini tentang ukuran/shape/allowlist input, bukan bypass authorization.

### GG-SEC-002 - CSRF check tidak fail-closed untuk Origin yang hilang

- **Severity:** Medium.
- **Lokasi:** `backend/app/core/security.py:104-114`.
- **Evidence:** mutation hanya ditolak bila `origin` ada dan tidak cocok. `Origin` kosong/absen langsung diteruskan; tidak ada synchronizer token/double-submit token.
- **Impact:** SameSite=Lax mengurangi CSRF browser lintas-site, tetapi client/proxy yang menghapus `Origin`, browser lama, atau integrasi non-browser dapat melewati defense-in-depth. Risiko meningkat bila cookie policy berubah atau ada endpoint mutation baru.
- **Fix:** untuk endpoint cookie-authenticated, wajibkan `Origin` yang cocok atau `Referer` yang cocok; tambahkan CSRF token untuk mutation. Pisahkan endpoint bearer-service dari kebijakan cookie CSRF.
- **Mitigasi:** pertahankan `HttpOnly`, `Secure`, `SameSite=Lax`, dan jangan menerima mutation dari host selain `APP_PUBLIC_ORIGIN`.
- **False-positive note:** ini bukan bukti exploit langsung pada browser modern; kategorinya hardening yang perlu ditutup sebelum production scale.

### GG-SEC-003 - CSP production mengizinkan inline script/style

- **Severity:** Medium.
- **Lokasi:** `frontend/next.config.ts:14-16`.
- **Evidence:** `style-src 'self' 'unsafe-inline'` dan `script-src 'self' 'unsafe-inline'` tetap aktif production; `unsafe-eval` memang hanya ditambah non-production.
- **Impact:** bila ada injection pada render/copy/data boundary, CSP memiliki lebih sedikit kemampuan membatasi payload inline.
- **Fix:** migrasikan inline bootstrap/style ke nonce/hash yang dikelola Next.js; pertahankan `unsafe-eval` hanya development. Audit Kumo/Next inline requirement sebelum memperketat agar tidak mematahkan runtime.
- **Mitigasi:** tetap pertahankan `default-src`, `frame-ancestors`, `object-src`, `connect-src`, COOP/CORP, dan output encoding React.
- **False-positive note:** pencarian source tidak menemukan `dangerouslySetInnerHTML`, `innerHTML`, atau `eval`; temuan ini adalah blast-radius hardening.

### GG-SEC-004 - Rate limiter single-process

- **Severity:** Medium (operational security).
- **Lokasi:** `backend/app/core/security.py:18-37`, `backend/app/api/operations.py:31-53`.
- **Evidence:** counter disimpan pada `dict/deque` proses dan `_SERVICE_RATE_LIMIT` juga in-memory.
- **Impact:** restart menghapus counter; replica kedua memiliki counter sendiri. Brute force, partner API flood, dan abuse endpoint dapat melewati batas nominal.
- **Fix:** letakkan rate limit bersama di ingress/WAF atau Redis dengan key IP/user/service-account; tambahkan throttle khusus login/password dan retry budget.
- **Mitigasi:** deploy satu replica hanya sebagai sementara dan monitor 429/latency.
- **False-positive note:** source sudah mendokumentasikan keterbatasan ini; temuan tetap berlaku untuk scale-out.

### GG-SEC-005 - Host header belum dibatasi di application boundary

- **Severity:** Medium.
- **Lokasi:** `backend/app/main.py:25-41`; `backend/app/core/config.py:81-108`.
- **Evidence:** CORS origin divalidasi, tetapi tidak ada `TrustedHostMiddleware`/allowlist hostname pada FastAPI.
- **Impact:** bila backend atau proxy salah terekspos, request dengan Host tidak terduga dapat masuk ke aplikasi dan menyulitkan pencegahan host confusion/cache poisoning.
- **Fix:** tambahkan `TrustedHostMiddleware` dengan hostname public yang eksplisit (dan hostname internal yang memang diperlukan), serta firewall agar FastAPI hanya menerima traffic dari frontend/ingress.
- **Mitigasi:** pastikan Caddy hanya meneruskan satu hostname, backend port tidak public, dan lakukan test Host header pada ingress.
- **False-positive note:** dokumentasi deployment menyatakan FastAPI private di belakang Caddy; kontrol edge harus diverifikasi di VM, bukan diasumsikan dari source.

### GG-SEC-006 - Residual DNS-rebinding SSRF pada webhook worker

- **Severity:** Medium.
- **Lokasi:** `backend/app/worker.py:126-149`, `backend/app/worker.py:236-251`.
- **Evidence:** worker memvalidasi seluruh alamat hasil `getaddrinfo` sebagai global, tetapi `httpx.Client` kemudian melakukan koneksi/resolusi sendiri. Redirect memang dimatikan.
- **Impact:** DNS dapat berubah antara pemeriksaan dan koneksi; worker berpotensi menghubungi alamat private/internal. Risiko terutama relevan bila admin dapat membuat subscription webhook dan worker memiliki akses jaringan luas.
- **Fix:** gunakan transport HTTP yang mengikat koneksi ke alamat yang sudah divalidasi, atau resolver/egress proxy yang mem-pin destination; set `trust_env=False`, blok private/link-local/metadata ranges di network layer, dan ulangi validasi setiap redirect/connection.
- **Mitigasi:** egress firewall hanya ke jaringan publik/allowlist tujuan; pertahankan `follow_redirects=False`.
- **False-positive note:** ada defense yang bermakna saat ini; ini residual TOCTOU, bukan bukti bahwa SSRF sudah exploitable pada semua deployment.

### GG-OPS-002 - Backup/restore dan ingress body limit belum terbukti

- **Severity:** Medium (release readiness).
- **Lokasi:** `docs/deployment.md:119-138`, `docker-compose.prod.yml`, `infra/gateguard-deploy-if-new.sh`.
- **Evidence:** docs mewajibkan backup/restore test dan ingress body limit, tetapi repo hanya mendefinisikan named volume Compose; tidak ada konfigurasi backup/restore scheduler atau Caddy body-limit test yang dapat diverifikasi dari checkout.
- **Impact:** kehilangan PostgreSQL/document volume atau upload besar dapat menjadi insiden data/availability; klaim production-ready belum memiliki bukti restore.
- **Fix:** dokumentasikan owner, RPO/RTO, encrypted backup, restore drill, retention, dan Caddy/app body limit; simpan smoke script yang gagal bila kontrol belum terpasang.
- **Mitigasi:** jangan pakai data pelanggan nyata sebelum backup restore berhasil di environment terpisah.

## UI/UX parity audit

- Kumo sudah menjadi basis utama komponen primitive (Banner, Badge, Dropdown, Input, Combobox, Select, Toolbar, Pagination, Tooltip, Loader, Switch, Toasty, Table) dan `@cloudflare/kumo@2.12.0` terpasang.
- Chart sudah menggunakan `@cloudflare/kumo` `TimeseriesChart` dengan Apache ECharts, bukan chart library acak. Namun dashboard masih punya satu import ECharts full bundle; konsolidasikan ke core imports agar bundle konsisten.
- Sidebar collapse sudah memakai transisi dan reduced-motion fallback. Filter reset sekarang punya opsi “Semua ...” yang benar-benar bisa dipilih; lebar select/combobox diseragamkan.
- Status raw utama sudah diterjemahkan di `OperationalState`/`StatusBadge`, termasuk `RELEASE_AUTHORIZED`, `REVIEW_REQUIRED`, `NOT_CONFIGURED`, `DEAD_LETTER`, dan severity. Sisa copy/filter literal di beberapa page masih perlu sweep sebelum klaim 100% parity.
- Route `/notifications` sudah ada di local build dan menunggu mutation `mark read` selesai sebelum navigasi. Route ini belum ada di live host (lihat GG-OPS-001).
- Klaim “100% pixel-identical Cloudflare pada 53 halaman” belum boleh dibuat tanpa screenshot regression per viewport; yang dapat diverifikasi sekarang adalah penggunaan Kumo + struktur/state parity dan build 62 route lokal.

## Kontrol yang sudah lulus / tidak menjadi temuan

- Backend test suite lulus ketika dijalankan dari `backend`: seluruh test selesai tanpa failure (satu failure dari root hanya karena fixture memakai path relatif `../samples`).
- Frontend: `npm test` 8/8 lulus; `npm run lint` lulus; `npm run build` lulus dan menghasilkan 62 route.
- `npm audit --omit=dev --audit-level=high`: 0 vulnerability.
- `pip-audit -r backend/requirements.txt`: tidak ada known vulnerability.
- `ruff check app tests` dan `python -m compileall -q app`: lulus.
- Session token opaque di-hash server-side; cookie login `HttpOnly`, `Secure` production, `SameSite=Lax`.
- CORS tidak memakai wildcard dengan credentials; API docs dimatikan production; security headers/HSTS diterapkan.
- Upload memeriksa extension, magic bytes, MIME mismatch, byte limit, image pixel limit, dan duplicate binary.
- Dokumen disimpan dengan storage key yang divalidasi dan download memakai `Content-Disposition: attachment`.
- Tidak ditemukan `dangerouslySetInnerHTML`, `innerHTML`, `eval`, `new Function`, subprocess shell sink, atau credential di `localStorage` pada source yang diaudit.

## Urutan kerja yang paling aman

1. Sinkronkan live ke SHA `57eda11...` dan buktikan route/readiness smoke test remote.
2. Tutup bounded-schema/body-limit gap (GG-SEC-001); ini prioritas sebelum menambah page baru.
3. Tambahkan host allowlist + CSRF fail-closed + shared rate limit sebelum scale-out.
4. Pin/egress-control webhook destination dan lakukan backup/restore drill.
5. Selesaikan status-copy sweep dan screenshot regression untuk seluruh page/component sebelum menyatakan Cloudflare parity final.

## Follow-up UI verification (25 Agustus 2026)

- Semua page-level error notice yang sebelumnya masih memakai `.notice`/`.notice--danger` sudah dipindahkan ke Kumo `Banner` melalui `StateNotice`; tidak ada lagi raw notice class di source TSX/TS.
- Filter/search surface sudah dipusatkan ke Kumo `Toolbar` + `InputGroup`; browser smoke test mengukur toolbar penuh 976 px pada viewport desktop dan select status tetap satu baris dengan lebar 168 px.
- Browser smoke test memverifikasi `/dashboard`, `/shipments`, `/settings`, `/governance/reference-data`, dan `/integrations/jobs`; sidebar collapse berpindah 240 px → 64 px, ikon search tetap terlihat, dan expand kembali ke 240 px.
- Frontend gates setelah perubahan: `npm test` 8/8, `npm run lint`, `npm run build` (62 route), `npm audit --omit=dev --audit-level=high` 0 vulnerability. Backend: `uv run pytest -q`, `uv run ruff check app tests`, dan `compileall` lulus.
- Ini memperkuat parity struktural/state, tetapi belum menjadi bukti pixel-identical untuk seluruh 53 halaman; screenshot regression per viewport dan sinkronisasi live tetap wajib.
