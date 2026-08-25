# Outurn — AI-Powered Pre-Dispatch Shipment Assurance

Outurn is a focused Smart Logistics MVP for warehouse and distribution teams. It checks one shipment before dispatch by reading an Invoice, Packing List, and Delivery Order; normalizing entities and addresses; reconciling critical fields; checking destination plausibility; explaining anomalies; and guiding a human through correction and revalidation.

The product answers one operational question: **is this shipment safe to release from the warehouse based on the evidence available right now?**

## Why it matters

Manual document comparison makes quantity mismatch, wrong SKU, wrong recipient, destination variation, and incomplete evidence easy to miss. Outurn makes those discrepancies visible before a shipment leaves the warehouse. AI extracts structured evidence, while deterministic rules keep the safety decision fail-closed.

## AIC theme alignment

Outurn is positioned under **AI for the Backbone of the Economy → Smart Logistics — Warehouse & Distribution**. It is not a generic document-management or transport-management system. Every screen is part of the single shipment assurance workflow.

## Main workflow

```text
Shipment intake
  → upload Invoice + Packing List + Delivery Order
  → AI document understanding with provenance and confidence
  → entity and address normalization
  → canonical shipment view and consistency matrix
  → on-demand OpenStreetMap/Nominatim destination verification
  → deterministic risk score and evidence-based explanation
  → recommended corrective action
  → replace a document and re-check synchronously
  → CLEAR / REVIEW / HOLD
```

The browser uses the main `/reconcile` workspace. Replacing a document runs validation, extraction, normalization, reconciliation, geocoding, risk scoring, and the final decision again in the same request. There is no worker, queue, scheduler, or polling requirement in the local MVP.

## Architecture

```text
Browser
  ↓
Next.js UI + server-side BFF
  ↓
FastAPI synchronous API
  ├─ bounded upload and PDF/image validation
  ├─ local extraction or server-side AI provider adapter
  ├─ canonical evidence and provenance
  ├─ semantic normalization and deterministic reconciliation
  ├─ on-demand geocoding adapter with graceful fallback
  └─ deterministic risk, explanation, and resolution audit
  ↓
SQLite
```

The baseline was imported from the existing GateGuard codebase rather than rewritten from scratch. Source baseline SHA: `576b74e9006cf5618a87b048ece267d4b3cb56cb`.

## AI responsibilities and safety boundary

AI/provider adapters may help with:

- document type and field extraction;
- structured line-item understanding;
- entity/address normalization guidance;
- evidence-grounded anomaly wording when a provider is configured.

The decision engine, confidence gate, geographic classification, risk score, and `CLEAR` / `REVIEW` / `HOLD` result are deterministic. Uploaded documents are untrusted data; extraction prompts explicitly instruct providers not to follow instructions found inside documents. API keys never reach the browser.

### Fine-tuning status — blocker is reported honestly

The repository does not contain a fabricated fine-tuned model ID or fabricated metrics. Set `AI_FINETUNED_MODEL_ID` only after a real provider fine-tuning job succeeds and the identifier is verified. Until then, the application uses the configured base/provider adapter and the competition fine-tuning requirement remains a **FINE-TUNING BLOCKER**, not a claimed pass.

The intended fine-tuning task is `shipment document → canonical structured shipment data`. See [data/fine_tuning/README.md](data/fine_tuning/README.md) for the synthetic dataset contract and limitations. The provider reference is the [OpenAI fine-tuning API](https://developers.openai.com/api/reference/resources/fine_tuning).

## Geospatial validation

The backend uses a configurable geocoder base URL and a deliberate, end-user-triggered Nominatim adapter. It sends a descriptive User-Agent, serializes requests at no more than one request per second, caches results for the process lifetime, does not implement autocomplete, and treats unavailable or ambiguous results as `GEOCODING_UNCERTAIN` / `REVIEW`.

The UI shows an OpenStreetMap embed only when coordinates are available and displays attribution. The base URL can be switched without a code change. Read the [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/) before using the public service with real operational data; do not submit confidential personal data.

## Run locally with Docker

Requirements: Docker Desktop or Docker Engine with Compose.

```bash
cp .env.example .env
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The API health endpoints are available at [http://localhost:8000/healthz](http://localhost:8000/healthz) and [http://localhost:8000/readyz](http://localhost:8000/readyz).

The local stack has only two application services:

- `backend`: FastAPI, SQLite, bounded document storage, synchronous processing;
- `frontend`: Next.js workspace and server-side API proxy.

## Environment

Copy `.env.example` to `.env`. The important values are:

```text
DATABASE_URL=sqlite:///./outurn.db
EXTRACTION_PROVIDER=openrouter
OPENROUTER_API_KEY=replace-with-your-openrouter-key
OPENROUTER_MODEL=stealth/ox-alpha
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-2024-08-06
AI_FINETUNED_MODEL_ID=
GEOCODING_BASE_URL=https://nominatim.openstreetmap.org
GEOCODING_USER_AGENT=Outurn/0.1 (shipment-assurance-demo)
```

Keep provider keys server-side and never commit `.env`.

## Synthetic sample cases

The repository includes synthetic, non-confidential fixtures:

| Case | Expected result | Demonstrates |
|---|---|---|
| `samples/clear` | `CLEAR` | all three documents agree |
| `samples/hold-quantity` | `HOLD` | Invoice/Delivery Order show 100 while Packing List shows 90 |
| `samples/review-destination` | `REVIEW` or `HOLD` | destination evidence is materially different or unresolved |
| `samples/entity-normalization` | `CLEAR` when safely equivalent | `PT. Maju Jaya` and `PT Maju Jaya` variation |

Run the sample generator after installing the backend development dependencies:

```bash
python scripts/generate_samples.py
```

## Tests and quality gates

Backend:

```bash
cd backend
uv sync --locked --extra dev
uv run pytest -q
uv run ruff check app tests
```

Frontend:

```bash
cd frontend
npm ci --include=dev
npm test
npm run lint
npm run build
```

Compose smoke checks:

```bash
docker compose config
docker compose build
```

The intended golden path is covered by the API and UI contracts: create context, upload three documents, extract, normalize, reconcile, geocode when needed, show risk and explanation, replace a document, re-check, and observe the new final decision.

## Submission documentation

- [AIC submission checklist](docs/aic-submission-checklist.md)
- [Dataset and fine-tuning contract](data/fine_tuning/README.md)
- [Architecture notes](docs/architecture.md)

The checklist covers the Proof of Work video, innovation video, proposal contents, timestamp visibility, and the seven-minute/five-minute limits. Videos are not generated automatically.

## Limitations

- A verified fine-tuned model is not present in this checkout; this is explicitly reported as a blocker.
- Geocoding is conservative and can return `REVIEW` when the public service is unavailable or ambiguous.
- Local extraction is strongest for text-based PDFs; image OCR requires a configured provider.
- A consistent document set is not proof that the physical shipment is correct; operators must verify material exceptions.
- This MVP does not replace a WMS, ERP, TMS, warehouse scan, or physical quantity check.

## Responsible AI

Outurn does not let an LLM authorize dispatch. It preserves raw values, normalized values, confidence, provider, and evidence regions; rejects invalid structured output; limits uploaded files; treats documents as prompt-injection input; and fails closed when evidence is incomplete or contradictory.
