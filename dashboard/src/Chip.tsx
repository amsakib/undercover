import type { Decision, Status } from "./api";
import { STATUS_LABELS } from "./format";

export function StatusChip({ status }: Readonly<{ status: Status }>) {
  return (
    <span className={`chip status-${status}`}>{STATUS_LABELS[status]}</span>
  );
}

const DECISION_LABELS: Record<Decision["decision"], string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};

export function DecisionChip({
  decision,
}: Readonly<{ decision: Decision["decision"] }>) {
  return (
    <span className={`chip decision-${decision}`}>
      {DECISION_LABELS[decision]}
    </span>
  );
}
