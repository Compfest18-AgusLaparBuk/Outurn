"use client";

import { FileIcon as File, FileArrowUpIcon as FileArrowUp, XIcon as X } from "@phosphor-icons/react";
import { LayerCard } from "@cloudflare/kumo/components/layer-card";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { validateFile } from "@/lib/validation";

export function UploadSlot({
  label,
  hint,
  file,
  onFile,
}: {
  label: string;
  hint: string;
  file: File | null;
  onFile: (file: File | null, error: string | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function accept(next: File | null) {
    if (!next) {
      setError(null);
      onFile(null, null);
      return;
    }
    const nextError = validateFile(next);
    setError(nextError);
    onFile(nextError ? null : next, nextError);
  }

  return (
    <LayerCard
      className={`shipment-upload-card ${drag ? "shipment-upload-card--dragging" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        accept(e.dataTransfer.files[0] || null);
      }}
      aria-label={`Upload ${label}`}
    >
      <div className="shipment-upload-card__header">
        <div>
          <h3>{label}</h3>
          <p>{hint}</p>
        </div>
        {file ? <File size={18} className="text-kumo-success" aria-hidden /> : <FileArrowUp size={18} className="text-kumo-neutral-750" aria-hidden />}
      </div>

      {file ? (
        <div className="shipment-upload-file">
          <div className="min-w-0">
            <div className="shipment-upload-file__name">{file.name}</div>
            <div className="shipment-upload-file__size">{(file.size / 1024).toFixed(0)} KB</div>
          </div>
          <Button variant="ghost" aria-label={`Remove ${label}`} onClick={() => accept(null)}>
            <X size={16} />
          </Button>
        </div>
      ) : (
        <Button
          type="button"
          variant="secondary"
          className="shipment-upload-button"
          onClick={() => inputRef.current?.click()}
        >
          Drop a file here or choose one
        </Button>
      )}

      <input
        ref={inputRef}
        type="file"
        className="sr-only"
        accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
        onChange={(e) => accept(e.currentTarget.files?.[0] || null)}
      />
      {error && <p className="mt-2 text-sm text-kumo-danger" role="alert">{error}</p>}
    </LayerCard>
  );
}
