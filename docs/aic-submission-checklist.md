# AIC 2026 submission checklist

This checklist is for final submission preparation and does not generate or edit videos automatically.

## Proof of Work

- [ ] Maximum 7 minutes.
- [ ] Shows the latest working MVP state with a visible timestamp.
- [ ] Shows intake, three uploads, extraction, reconciliation, destination verification, risk, explanation, correction, re-check, and final decision.
- [ ] Does not use hard cuts to hide a broken or incomplete state; only normal waiting-time acceleration is used.
- [ ] Upload to YouTube as `Unlisted`.
- [ ] Naming: `COMPFEST 18 AIC: PROOF OF WORK - [Team] - [Project]`.

## Innovation video

- [ ] MP4, at least 720p, maximum 5 minutes.
- [ ] Explains the design process, industry problem, AI contribution, and practical benefit.
- [ ] Upload to YouTube as `Unlisted`.
- [ ] Naming: `COMPFEST 18 AIC: [Team] - [Project]`.

## Proposal

- [ ] PDF is at most 20 pages excluding cover, references, and appendix.
- [ ] Contains project name, background, goals and benefits, methodology, dataset acquisition, model development per feature, code integration, technical rationale, and conclusion.
- [ ] Dataset and model claims match repository evidence; no fabricated benchmark or fine-tuning result.

## Repository readiness

- [ ] No secrets or real customer documents.
- [ ] Synthetic samples and dataset provenance are documented.
- [ ] `cp .env.example .env && docker compose up --build` is reproducible.
- [ ] Final repository is public only after the target and contents are confirmed.
- [ ] Final commits use `feat:`, `fix:`, or `refactor:` with a descriptive message.
