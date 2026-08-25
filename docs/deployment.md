# Deployment

Dokumen ini menjelaskan deployment minimum Outurn untuk submission AIC dan pengujian terkontrol. Dokumen ini bukan pengganti security control organisasi yang menjalankan aplikasi.

## Topologi Runtime

```text
Internet
  │ HTTPS
  ▼
Caddy pada Azure VM
  │ localhost:3000
  ▼
Next.js console + BFF
  │ private Docker network
  ▼
FastAPI synchronous API ─── PostgreSQL (production profile)
  │
  └── document volume

Azure Key Vault ── managed identity VM ── runtime secrets
```

FastAPI dan PostgreSQL tidak diekspos langsung ke Internet. Caddy menjadi ingress TLS dan frontend meneruskan request API melalui BFF.

## Konfigurasi Wajib

Mulai dari `.env.production.example` dan ganti seluruh placeholder. Production minimal memerlukan:

- `APP_ENV=production`
- `APP_PUBLIC_ORIGIN` dengan origin HTTPS yang benar;
- `CORS_ORIGINS` yang eksplisit;
- `APP_API_KEY` minimal 32 karakter;
- `WEBHOOK_SECRET_KEY` minimal 32 karakter;
- `COOKIE_SECURE=true`;
- `POSTGRES_PASSWORD` dan `DATABASE_URL` PostgreSQL;
- `EXTRACTION_PROVIDER=openrouter` untuk jalur extraction MVP;
- `OPENROUTER_API_KEY` diisi dengan key OpenRouter dan `OPENROUTER_MODEL=stealth/ox-alpha`.

`APP_API_KEY` adalah credential server-to-server yang hanya digunakan oleh Next.js BFF. Autentikasi manusia memakai user database dan opaque session cookie; tidak ada shared supervisor credential.

Provider key harus tetap berada di server. Jangan pernah mengeksposnya melalui `NEXT_PUBLIC_*`, browser, log, fixture, Docker image, atau GitHub Actions.

## Menjalankan Compose

```bash
cp .env.production.example .env
# isi semua secret melalui secret manager atau environment lokal yang aman
docker compose -f docker-compose.prod.yml up --build
```

Compose menjalankan PostgreSQL, migration one-shot, seed user, FastAPI, dan Next.js. Pemrosesan shipment tetap synchronous pada request; tidak ada worker, queue, scheduler, atau polling service. Container menggunakan non-root user, capability yang dibatasi, named volume untuk dokumen, serta health check untuk PostgreSQL dan FastAPI.

## Bootstrap Azure

Bootstrap resmi berada di `infra/bootstrap-outurn-azure.sh`. Jalankan dari Azure Cloud Shell setelah login dengan subscription target:

```bash
curl -fsSL https://raw.githubusercontent.com/Compfest18-AgusLaparBuk/Outurn/main/infra/bootstrap-outurn-azure.sh | bash
```

Script tersebut membuat resource group, provider registration, Key Vault RBAC, Ubuntu VM, managed identity, network rule minimum, Caddy, systemd timer, dan secret runtime. Script meminta OpenRouter key serta password bootstrap melalui prompt tersembunyi; nilainya tidak ditulis ke repository.

Bootstrap memakai Key Vault sebagai source of truth. VM mengambil secret dengan managed identity, menulis `.env` runtime dengan permission ketat, lalu menjalankan deployment pertama. Jika Cloud Shell terputus, periksa resource group terlebih dahulu sebelum mengulang bootstrap agar tidak membuat resource duplikat.

## Automatic Deployment

GitHub Actions menjalankan quality gate pada push/pull request: test backend dan frontend, lint, build, migration smoke test, Compose validation, dependency audit, Semgrep, Gitleaks, Trivy, image scan, dan SBOM. Tidak ada publish image, registry credential, atau secret aplikasi di workflow.

Setelah VM bootstrap selesai, `outurn-deploy.timer` memeriksa branch `main` setiap lima menit. Service `outurn-deploy` menjalankan urutan berikut:

```text
fetch origin/main
  → checkout SHA target
  → docker compose up -d --build
  → tunggu PostgreSQL dan FastAPI healthy
  → cek /login
  → simpan SHA terakhir yang sukses
```

Lock file mencegah deployment tumpang tindih. Bila health check gagal, service menampilkan status dan log Compose tanpa menandai SHA sebagai sukses; percobaan berikutnya dapat melakukan retry.

Perintah inspeksi pada VM:

```bash
sudo systemctl status outurn-deploy.timer
sudo systemctl status outurn-deploy.service
sudo journalctl -u outurn-deploy.service -n 100 --no-pager
cat /var/lib/outurn/last-successful-sha
docker compose -f /opt/outurn/docker-compose.prod.yml ps
```

## Dependency Locking

Versi dependency tingkat atas dibatasi pada `backend/pyproject.toml` dan `frontend/package.json`; lockfile yang direview adalah `backend/uv.lock`, `frontend/package-lock.json`, dan `frontend/pnpm-lock.yaml` bila digunakan oleh workflow lokal.

```bash
./scripts/generate_locks.sh
```

Review perubahan lockfile sebelum commit. Jangan mengandalkan dependency global yang tidak dipin.

## Ingress dan Authentication

Sebelum mengarahkan traffic pengguna:

- gunakan origin HTTPS dan CORS yang sama;
- arahkan traffic publik hanya ke Caddy/Next.js;
- simpan FastAPI pada jaringan internal Compose;
- jalankan migration sebelum API menerima traffic;
- bootstrap admin dengan `backend/scripts/create_admin.py` atau seed secret dari Key Vault;
- enforce supervisor override melalui backend RBAC;
- tetapkan body limit pada ingress dan aplikasi;
- gunakan rate limiter bersama bila deployment berubah menjadi multi-instance.

Domain `sslip.io` dari bootstrap cocok untuk smoke test dan submission preview. Gunakan domain organisasi sendiri sebelum penggunaan bisnis jangka panjang.

## Penanganan Data dan Backup

Dokumen shipment dapat memuat data pelanggan dan data komersial. Tetapkan kebijakan retensi serta akses sebelum memakai dokumen nyata.

Dokumen upload berada pada named volume dan harus tercakup oleh retensi serta backup organisasi. PostgreSQL membutuhkan automated backup, restore procedure, credential rotation, migration recovery, dan uji pemulihan berkala. Backup yang belum pernah dipulihkan di test environment tidak boleh dianggap tervalidasi.

## Health Check

- `/healthz` mengonfirmasi proses API hidup.
- `/readyz` mengonfirmasi service dapat memakai repository/schema yang dikonfigurasi.
- `/api/health/ready` pada frontend memeriksa readiness backend melalui BFF.
- `/login` dipakai deployment timer sebagai smoke check route frontend.

Gunakan readiness, bukan liveness, untuk menentukan apakah service dapat menerima traffic.
