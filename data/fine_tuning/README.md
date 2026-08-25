# Synthetic shipment-document fine-tuning dataset

This directory documents the intended training input for the AIC domain task:

```text
shipment document → canonical structured shipment data
```

The examples are synthetic. They were authored for this repository from invented shipment references, parties, addresses, SKUs, and quantities. They are not copied from a customer or private operational system. The dataset contains no API keys, personal identifiers, or confidential documents.

## Dataset contract

- Format: JSONL, one supervised example per line.
- Main use case: document-type classification and extraction of recipient, destination, shipment reference, and line items.
- Secondary use case: semantic entity/address normalization examples.
- Classes: `invoice`, `packing_list`, `delivery_order`, plus normalization labels `SAME`, `LIKELY_SAME`, `DIFFERENT`, and `UNCERTAIN`.
- Cleaning: whitespace is normalized, examples are bounded, quantities are numeric, and unsupported fields are omitted instead of guessed.
- Split: this starter manifest contains development examples only. It does not claim a train/validation benchmark or model metric. Create a separate immutable train/validation split before submitting a real fine-tuning job.

## Why synthetic data

The MVP needs domain-shaped evidence without exposing real shipment information. Synthetic documents let the team cover quantity mismatch, address variation, missing evidence, and recipient ambiguity while keeping provenance clear.

## Limitations

This is a small starter dataset, not a performance claim. It does not represent OCR noise, multilingual scans, handwritten forms, every carrier layout, or the full distribution of Indonesian addresses. A real fine-tuning submission must add a larger documented set, validate it independently, record the provider job ID, and report real results only.

## Static model requirement

Runtime never trains, self-learns, collects new examples, or tunes parameters. Set `AI_FINETUNED_MODEL_ID` only to a verified model identifier produced by a real provider job. Until then, the repository reports `FINE-TUNING BLOCKER`.
