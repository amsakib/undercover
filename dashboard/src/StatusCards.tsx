import type { ClaimRow, Status } from "./api";
import { STATUS_LABELS } from "./format";

const ORDER: Status[] = [
  "waiting",
  "in_progress",
  "awaiting_signoff",
  "needs_handler",
  "decided",
];

export function StatusCards({ claims }: Readonly<{ claims: ClaimRow[] }>) {
  return (
    <ul className="kpis" aria-label="Claims by status">
      <li className="kpi">
        <span className="kpi-value">{claims.length}</span>
        <span className="kpi-label">Claims</span>
      </li>
      {ORDER.map((status) => (
        <li key={status} className={`kpi kpi-${status}`}>
          <span className="kpi-value">
            {claims.filter((c) => c.status === status).length}
          </span>
          <span className="kpi-label">{STATUS_LABELS[status]}</span>
        </li>
      ))}
    </ul>
  );
}
