import { useEffect, useState } from "react";
import { api, POLL_MS, type ClaimRow } from "./api";
import { StatusChip } from "./Chip";
import { label, money } from "./format";

export function QueuePage() {
  const [claims, setClaims] = useState<ClaimRow[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const load = () => {
      api
        .claims()
        .then((rows) => {
          setClaims(rows);
          setError(false);
        })
        .catch(() => {
          setError(true);
        });
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      clearInterval(timer);
    };
  }, []);

  if (error && !claims)
    return <p className="panel">The backend is not responding.</p>;
  if (!claims) return <p className="panel">Loading the queue.</p>;

  const count = (status: ClaimRow["status"]) =>
    claims.filter((c) => c.status === status).length;

  return (
    <section className="panel">
      <div className="panel-head">
        <h1>Claims queue</h1>
        <p className="muted">
          {claims.length} claims · {count("waiting")} waiting ·{" "}
          {count("awaiting_signoff")} waiting for sign-off · {count("decided")}{" "}
          decided
        </p>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Claim</th>
              <th>Type</th>
              <th>Summary</th>
              <th>Submitted</th>
              <th className="num">Claimed</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim) => (
              <tr key={claim.claim_id}>
                <td>
                  <a className="mono" href={`#/claims/${claim.claim_id}`}>
                    {claim.claim_id}
                  </a>
                </td>
                <td>{label(claim.claim_type)}</td>
                <td>{claim.summary}</td>
                <td className="mono">{claim.submitted_on}</td>
                <td className="num mono">{money(claim.amount_claimed)}</td>
                <td>
                  <StatusChip status={claim.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
