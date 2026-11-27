import { useEffect, useState } from "react";
import { api, POLL_MS, type ClaimRow, type Run } from "./api";
import { DecisionChip, StatusChip } from "./Chip";
import { label, money } from "./format";
import { RunPanel } from "./RunPanel";
import { StatusCards } from "./StatusCards";

export function QueuePage() {
  const [claims, setClaims] = useState<ClaimRow[] | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const load = () => {
      Promise.all([api.claims(), api.latestRun()])
        .then(([rows, latest]) => {
          setClaims(rows);
          setRun(latest);
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

  return (
    <>
      <StatusCards claims={claims} />
      {run && <RunPanel run={run} />}
      <section className="panel">
        <div className="panel-head">
          <h1>Claims queue</h1>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Claim</th>
                <th>Customer</th>
                <th>Type</th>
                <th>Summary</th>
                <th>Submitted</th>
                <th className="num">Claimed</th>
                <th>Status</th>
                <th>Decision</th>
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
                  <td>{claim.customer_name}</td>
                  <td>{label(claim.claim_type)}</td>
                  <td>{claim.summary}</td>
                  <td className="mono">{claim.submitted_on}</td>
                  <td className="num mono">{money(claim.amount_claimed)}</td>
                  <td>
                    <StatusChip status={claim.status} />
                  </td>
                  <td>
                    {claim.decision ? (
                      <span className="decision-cell">
                        <DecisionChip decision={claim.decision.decision} />
                        <span className="mono">
                          {money(claim.decision.payout)}
                        </span>
                      </span>
                    ) : (
                      <span className="muted">None yet</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
