# Outurn

### AI Innovation Challenge 2026 — Logistics & Supply Chain

Outurn adalah console assurance pra-pengiriman yang memeriksa konsistensi **Delivery Order**, **Invoice**, dan **Packing List** sebelum shipment dapat dilepas. Fokusnya bukan membuat keputusan dari jawaban model, melainkan mengubah dokumen menjadi evidence yang dapat ditelusuri lalu menjalankan rekonsiliasi deterministik dengan hasil `CLEAR`, `REVIEW`, atau `HOLD`.

> **Satu workflow utama:** upload → extract → ground → reconcile → approve/review.

## Ringkasan Eksekutif

Di lapangan, satu shipment sering direpresentasikan oleh beberapa dokumen dengan format dan penulisan yang berbeda. Kesalahan kecil pada nomor dokumen, SKU, tujuan, kuantitas, atau total dapat lolos bila dokumen diperiksa terpisah.

Outurn menyatukan pemeriksaan itu ke satu rekam operasional. Model hanya membantu ekstraksi evidence. Sistem tetap memvalidasi file, menyimpan provenance, membandingkan field penting secara deterministik, dan meminta review manusia ketika bukti tidak lengkap atau konflik tidak aman untuk diselesaikan otomatis.

| Masalah | Pendekatan Outurn |
|---|---|
| Dokumen tersebar dan sulit dibandingkan | Satu shipment case dengan evidence lintas dokumen |
| Hasil AI sulit ditelusuri | Nilai disertai sumber, confidence, dan status verifikasi |
| Mismatch kecil berisiko menjadi false-clear | Rekonsiliasi konservatif dengan keputusan fail-closed |
| Approval tidak memiliki jejak yang jelas | Audit trail, role enforcement, dan supervisor override yang immutable |

## Fitur Utama

1. **Shipment register** — membuat dan memantau case shipment dari satu console.
2. **Three-document intake** — menerima Delivery Order, Invoice, dan Packing List dengan validasi MIME, signature, ukuran, halaman, dan pixel limit.
3. **Evidence extraction** — menormalisasi identitas, tujuan, line item, kuantitas, dan total ke canonical shipment schema.
4. **Evidence grounding** — menghubungkan nilai hasil ekstraksi ke sumber dokumen dan mempertahankan confidence serta provenance.
5. **Deterministic reconciliation** — membandingkan field kritis dan line item tanpa menyerahkan keputusan release kepada model.
6. **Release decision** — menghasilkan `CLEAR`, `REVIEW`, atau `HOLD` dengan alasan yang dapat dibaca operator.
7. **Human review** — supervisor dapat mencatat override dengan actor, alasan, keputusan awal, keputusan akhir, dan timestamp.
8. **Operational console** — work queue, exception, screening, dangerous goods, audit, analytics, observability, integrations, governance, dan settings.
9. **Role-based access** — `operator`, `supervisor`, dan `admin` ditegakkan di backend; kontrol UI bukan batas keamanan.

## AI/ML yang Dikustomisasi untuk Outurn

Outurn tidak melakukan zero-shot API call lalu menerima hasil mentah. Lapisan adaptasinya terdiri dari:

- **Local RAG playbook**: guidance domain disimpan di source code, diranking berdasarkan tipe dokumen dan istilah yang ditemukan pada teks dokumen.
- **Forced tool calling**: provider hanya diarahkan ke function `emit_shipment_document` dengan schema field yang eksplisit.
- **Schema dan safety validation**: payload tool divalidasi, line item wajib lengkap untuk jalur OpenRouter, dan output provider tetap diperlakukan sebagai evidence tidak tepercaya.
- **Grounding dan deterministic gate**: evidence dikorelasikan, confidence diperiksa, lalu aturan rekonsiliasi menentukan status operasional.
- **Human-in-the-loop**: ambiguity atau konflik material berubah menjadi `REVIEW`/`HOLD`; model tidak dapat menjalankan tool eksternal atau mengesahkan release.

Konfigurasi provider berada di backend melalui `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, dan `OPENROUTER_BASE_URL`. Key tidak pernah diletakkan pada `NEXT_PUBLIC_*`, browser, fixture, atau Git.

## Workflow Utama AIC

```text
1. Upload tiga dokumen wajib
        |
2. Validasi file + ekstraksi dengan local RAG playbook dan forced tool
        |
3. Simpan evidence, provenance, confidence, dan hasil normalisasi
        |
4. Rekonsiliasi identitas, tujuan, item, kuantitas, dan total
        |
5. CLEAR / REVIEW / HOLD
        |
6. Supervisor review atau override tercatat pada audit trail
```

Setiap tahap membutuhkan hasil tahap sebelumnya. Tidak ada menu AI yang berdiri sendiri dan tidak ada jalur yang melewati evidence atau rekonsiliasi untuk langsung mengubah status release.

## UI dan Kumo

Frontend menggunakan [Cloudflare Kumo](https://kumo-ui.com/) sebagai primitive UI utama dengan visual console yang mengikuti pola Cloudflare: sidebar rapat ke viewport, mode collapsed yang menyisakan logo/expand affordance, table operasional, page header, layer card, dan status yang konsisten.

Komponen Kumo yang dipakai di source code meliputi `CloudflareLogo`, `Sidebar`, `Button`, `Badge`, `Banner`, `Checkbox`, `Collapsible`, `Combobox`, `Dialog`, `Dropdown`, `Empty`, `Grid`, `Input`, `InputGroup`, `LayerCard`, `Loader`, `Pagination`, `Select`, `Switch`, `Table`, `Tabs`, `Toolbar`, `Toast`, `Tooltip`, serta chart `TimeseriesChart`.

Search global dan workspace switcher yang tidak memberi nilai pada workflow utama tidak menjadi pusat navigasi. Navigasi diarahkan ke case, evidence, assurance, keputusan, audit, dan pengaturan yang benar-benar dipakai operator.

## Arsitektur Sistem

```text
Browser
  │
  ▼
Next.js console + server-side BFF
  │  HttpOnly session cookie
  │  backend service credential tetap di server
  ▼
FastAPI modular monolith
  ├── authentication, sessions, RBAC, audit, four-eyes approval
  ├── shipment lifecycle, work queue, document storage
  ├── extraction router, local RAG playbook, OpenRouter tool adapter
  ├── evidence grounding, assurance rules, deterministic reconciliation
  └── integrations, webhooks, analytics, observability
  │
  ├── SQLite untuk local development dan test
  └── PostgreSQL untuk deployment production
```

Dokumen upload dan output provider diperlakukan sebagai input tidak tepercaya. Browser tidak menerima provider key, database password, backend service key, atau session token melalui JavaScript.

## Struktur Direktori

```text
.
├── backend/
│   ├── app/                 # API, domain, auth, extraction, reconciliation
│   ├── alembic/             # migration database
│   ├── scripts/             # bootstrap admin dan operational checks
│   └── tests/               # unit, API, security, extraction, workflow tests
├── frontend/
│   ├── app/                 # route dan page console
│   ├── components/          # workflow components dan Kumo wrappers
│   ├── lib/                 # API client, access, locale, validation
│   └── tests/               # Vitest + Testing Library
├── evaluation/              # synthetic rule dan extraction evaluation
├── docs/                    # architecture, quality, readiness, deployment
├── infra/                   # Azure bootstrap, pull deployment, systemd timer
├── samples/                 # fixture aman untuk development
├── scripts/                 # utility repository dan sample generator
├── docker-compose.yml       # local stack
└── docker-compose.prod.yml  # production stack
```

## Teknologi dan Dependensi

| Layer | Teknologi |
|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind CSS, Cloudflare Kumo, TanStack Query, ECharts |
| Backend | FastAPI, Pydantic Settings, SQLAlchemy, Alembic, psycopg, uv |
| Document pipeline | pypdf, pdfplumber, Pillow, OpenCV, RapidFuzz, OpenRouter adapter |
| Data | SQLite untuk local/test, PostgreSQL untuk production |
| Security | Argon2id, HttpOnly session, RBAC, rate limit, audit trail, secret store |
| Runtime | Docker Compose, Caddy, Azure VM, systemd pull timer |
| Quality | Pytest, Ruff, Vitest, Testing Library, Semgrep, Gitleaks, Trivy, SBOM |

## Instalasi dan Menjalankan Aplikasi

### Prasyarat

- Python 3.11+
- Node.js 22+
- `uv`
- Docker Desktop atau Docker Engine + Compose

### Cara cepat dengan Compose

```bash
cp .env.example .env
docker compose up --build
```

Console tersedia di `http://localhost:3000` dan API di `http://localhost:8000`.

### Menjalankan service terpisah

```bash
cd backend
uv sync --locked --extra dev
uv run alembic upgrade head
uv run python scripts/create_admin.py
uv run uvicorn app.main:app --reload --port 8000
```

Pada terminal lain:

```bash
cd frontend
npm ci --include=dev
npm run dev
```

Password, service key, dan provider key hanya diisi melalui environment lokal atau secret store. Jangan memasukkannya ke commit.

## Konfigurasi dan Secret Handling

File `.env.example` dan `.env.production.example` hanya berisi placeholder. Untuk Azure, `infra/bootstrap-outurn-azure.sh` membuat resource group, Key Vault dengan RBAC, VM, identity, Caddy, dan pull deployment. Secret production dimasukkan ke Key Vault lalu diambil VM menggunakan managed identity; tidak ada secret yang dikirim lewat GitHub Actions.

Variable yang umum dibutuhkan:

```text
APP_ENV=development|production
APP_PUBLIC_ORIGIN=https://your-origin.example
DATABASE_URL=...
APP_API_KEY=...
WEBHOOK_SECRET_KEY=...
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-4o-mini
```

Gunakan HTTPS untuk provider base URL pada production, CORS origin eksplisit, `COOKIE_SECURE=true`, PostgreSQL, dan secret minimal 32 karakter untuk credential aplikasi.

## Pengujian dan Quality Gate

Perubahan tidak dianggap selesai hanya karena halaman dapat dibuka. Jalankan:

```bash
make test

cd frontend
npm test
npm run lint
npm run build
```

Untuk workflow dokumen dan evaluasi:

```bash
cd backend
uv run pytest -q tests/test_openrouter_extractor.py tests/test_adversarial_extraction.py
uv run python ../evaluation/run.py
```

UI diverifikasi pada jalur yang dipakai operator: login, collapsed sidebar, shipment register, upload tiga dokumen, evidence result, status `CLEAR`/`REVIEW`/`HOLD`, dialog override, dan navigasi audit. Smoke check browser menggunakan Playwright CLI; assertion component tetap berada pada Vitest + Testing Library agar bisa berjalan deterministik di CI.

CI juga memeriksa migration smoke test, Compose configuration, shell syntax, dependency audit, Semgrep, Gitleaks, Trivy, dan SBOM.

## Deployment Azure dan CI/CD

Deployment target menggunakan Azure VM Linux dengan PostgreSQL di Compose, Caddy sebagai TLS ingress, dan Key Vault sebagai secret store. Setelah bootstrap pertama selesai, VM menjalankan pull deployment berbasis systemd timer. Timer mengambil `main`, memeriksa perubahan, menjalankan migration, build, health check, dan hanya mengaktifkan release yang lolos.

GitHub Actions menjalankan quality gate pada push/pull request. Pipeline tidak memakai bot publish image, registry credential, atau secret aplikasi. Polanya sengaja sederhana untuk resource Azure for Students: CI memverifikasi source, VM yang sudah memiliki managed identity menarik perubahan dari repository.

```text
push / pull request
        │
        ▼
GitHub Actions: test → lint → build → security scan
        │
        ▼
Azure VM timer: pull → migrate → build → health check → activate
```

Detail topology, rollback, health endpoint, dan bootstrap tersedia di [docs/deployment.md](docs/deployment.md).

## Kesesuaian dengan AIC Rulebook

- **Kustomisasi model**: local RAG playbook, forced function calling, schema validation, evidence grounding, dan deterministic policy engine.
- **Satu workflow utama**: seluruh fitur utama terhubung dari intake dokumen sampai keputusan release dan audit.
- **Human oversight**: hasil ambiguous tidak dipaksa menjadi `CLEAR`; supervisor menjadi bagian dari jalur review.
- **Reproducibility**: fixture, migration, evaluation script, lockfile, CI, dan security scan berada di repository.
- **Responsible AI**: dokumen diperlakukan sebagai data tidak tepercaya; prompt injection tidak boleh mengubah policy, memanggil tool, atau membocorkan secret.

## Status dan Batasan

Outurn adalah submission AIC tahap penyisihan. Dataset produksi berlabel belum dipublikasikan, sehingga repository tidak mengklaim akurasi provider, false-clear rate, latency, atau cost benchmark tanpa ground truth dan manifest yang terversi.

Outurn tidak menggantikan WMS/ERP/TMS, tidak memverifikasi isi fisik paket, tidak mengotorisasi pembayaran, dan tidak menjadikan konsistensi tiga dokumen sebagai bukti bahwa order tersebut benar secara eksternal.

## Roadmap

1. Menambah fixture dokumen berlabel dan redacted untuk benchmark extraction.
2. Menambah review queue yang diprioritaskan berdasarkan risiko dan confidence.
3. Menghubungkan referensi shipment tepercaya dari WMS/ERP.
4. Mengukur false-clear rate dengan dataset yang memiliki reviewer label.
5. Menambahkan object storage adapter setelah kebutuhan scale-out disetujui.

## Kontribusi dan Lisensi

Sebelum mengubah source, baca [CONTRIBUTING.md](CONTRIBUTING.md), [architecture guide](docs/architecture.md), dan [security policy](SECURITY.md). Jangan commit credential, dokumen pelanggan, log production, atau screenshot yang berisi data sensitif.

Lisensi dan ketentuan submission mengikuti aturan yang ditetapkan oleh tim dan penyelenggara AIC.
