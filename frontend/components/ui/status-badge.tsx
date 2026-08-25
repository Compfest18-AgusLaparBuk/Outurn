import { Badge } from "@cloudflare/kumo/components/badge";
import type { ReconciliationStatus } from "@/lib/types";
import { operationalStatusLabel } from "@/components/ui/operational-primitives";

const statusVariant = {
  CLEAR: "success",
  REVIEW: "warning",
  HOLD: "error",
} as const;

export function StatusBadge({ status }: { status: ReconciliationStatus }) {
  return (
    <span
      title={operationalStatusLabel(status)}
      aria-label={operationalStatusLabel(status)}
    >
      <Badge variant={statusVariant[status]} appearance="dot">
        {operationalStatusLabel(status)}
      </Badge>
    </span>
  );
}
