import type { Decision, Status, Todo } from "./api";
import { STATUS_LABELS, TODO_LABELS } from "./format";

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

export function TodoChip({ status }: Readonly<{ status: Todo["status"] }>) {
  return <span className={`chip todo-${status}`}>{TODO_LABELS[status]}</span>;
}
