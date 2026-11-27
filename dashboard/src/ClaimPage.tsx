import { useCallback, useEffect, useState } from "react";
import { Activity } from "./Activity";
import { api, POLL_MS, type Claim, type Policy, type Step } from "./api";
import { DecisionChip, StatusChip } from "./Chip";
import { label, money } from "./format";
import { SignOff } from "./SignOff";

function DecisionPanel({ claim }: Readonly<{ claim: Claim }>) {
  const { decision, payment } = claim;
  if (!decision) {
    return (
      <section className="panel">
        <h2>Decision</h2>
        <p className="muted">The agent has not decided this claim yet.</p>
      </section>
    );
  }
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Decision</h2>
        <DecisionChip decision={decision.decision} />
      </div>
      <p className="payout mono">{money(decision.payout)}</p>
      <p>{decision.reasons}</p>
      <p className="muted">Policy wording: {decision.policy_section}</p>
      {decision.signed_off_by && (
        <p className="muted">Signed off by {decision.signed_off_by}</p>
      )}
      {payment ? (
        <p className="muted">
          Paid {money(payment.amount)} by {payment.paid_by}
        </p>
      ) : (
        decision.decision === "approve" && <p className="muted">Not paid yet</p>
      )}
    </section>
  );
}

function ReadPanel({ steps }: Readonly<{ steps: Step[] }>) {
  const reads = [
    ...new Set(steps.filter((s) => s.kind === "read").map((s) => s.text)),
  ];
  return (
    <section className="panel">
      <h2>What the agent read</h2>
      {reads.length === 0 ? (
        <p className="muted">
          The agent has not read the wording or the manual yet.
        </p>
      ) : (
        <ul className="reads">
          {reads.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PolicyPanel({ policy }: Readonly<{ policy: Policy }>) {
  return (
    <section className="panel">
      <h2>Policy</h2>
      <dl>
        <dt>Policy</dt>
        <dd className="mono">{policy.policy_id}</dd>
        <dt>Plan</dt>
        <dd>{label(policy.plan)}</dd>
        <dt>Add-ons</dt>
        <dd>
          {policy.add_ons.length
            ? policy.add_ons.map(label).join(", ")
            : "None"}
        </dd>
        <dt>Bought</dt>
        <dd className="mono">{policy.purchased_on}</dd>
        <dt>Trip</dt>
        <dd>
          {policy.trip.destination},{" "}
          <span className="mono">
            {policy.trip.departs_on} to {policy.trip.returns_on}
          </span>
        </dd>
        <dt>Trip cost</dt>
        <dd className="mono">{money(policy.trip.trip_cost)}</dd>
        <dt>Travelers</dt>
        <dd>{policy.travelers.join(", ")}</dd>
      </dl>
    </section>
  );
}

function ClaimPanel({ claim }: Readonly<{ claim: Claim }>) {
  return (
    <section className="panel">
      <h2>{claim.summary}</h2>
      <p className="muted">
        {label(claim.claim_type)} · {claim.incident_location} · incident{" "}
        <span className="mono">{claim.incident_date}</span> · submitted{" "}
        <span className="mono">{claim.submitted_on}</span>
      </p>
      <p className="story">{claim.story}</p>
      <h3>Items claimed</h3>
      <table>
        <tbody>
          {claim.items.map((item) => (
            <tr key={item.description}>
              <td>{item.description}</td>
              <td>{label(item.category)}</td>
              <td className="num mono">{money(item.amount)}</td>
            </tr>
          ))}
          <tr className="total">
            <td colSpan={2}>Total claimed</td>
            <td className="num mono">{money(claim.amount_claimed)}</td>
          </tr>
        </tbody>
      </table>
      <h3>Documents</h3>
      {claim.documents.map((doc) => (
        <article className="document" key={doc.name}>
          <h4>{doc.name}</h4>
          <p>{doc.content}</p>
        </article>
      ))}
    </section>
  );
}

export function ClaimPage({ claimId }: Readonly<{ claimId: string }>) {
  const [claim, setClaim] = useState<Claim | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [missing, setMissing] = useState(false);

  const load = useCallback(() => {
    api
      .claim(claimId)
      .then((result) => {
        setClaim(result);
        return api.steps(claimId);
      })
      .then(setSteps)
      .catch(() => {
        setMissing(true);
      });
  }, [claimId]);

  useEffect(load, [load]);

  const policyId = claim?.policy_id;
  useEffect(() => {
    if (policyId) void api.policy(policyId).then(setPolicy);
  }, [policyId]);

  const status = claim?.status;
  useEffect(() => {
    if (status !== "in_progress") return;
    const timer = setInterval(load, POLL_MS);
    return () => {
      clearInterval(timer);
    };
  }, [status, load]);

  if (missing) return <p className="panel">There is no claim {claimId}.</p>;
  if (!claim) return <p className="panel">Loading {claimId}.</p>;

  return (
    <>
      <a href="#/">Back to the queue</a>
      <div className="page-head">
        <h1 className="mono">{claim.claim_id}</h1>
        <StatusChip status={claim.status} />
        {claim.attempts > 0 && (
          <span className="muted">
            Failed {claim.attempts} {claim.attempts === 1 ? "time" : "times"}
          </span>
        )}
      </div>
      <div className="claim-grid">
        <div className="column">
          <DecisionPanel claim={claim} />
          {claim.status === "awaiting_signoff" && (
            <SignOff claim={claim} onSigned={setClaim} />
          )}
          <ClaimPanel claim={claim} />
        </div>
        <div className="column">
          {policy && <PolicyPanel policy={policy} />}
          <ReadPanel steps={steps} />
          <Activity steps={steps} working={claim.status === "in_progress"} />
        </div>
      </div>
    </>
  );
}
