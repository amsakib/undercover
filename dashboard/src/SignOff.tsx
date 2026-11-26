import { useEffect, useState } from "react";
import { api, type Claim, type Handler } from "./api";
import { money } from "./format";

export function SignOff({
  claim,
  onSigned,
}: Readonly<{ claim: Claim; onSigned: (claim: Claim) => void }>) {
  const [handlers, setHandlers] = useState<Handler[]>([]);
  const [handlerId, setHandlerId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    void api.handlers().then((list) => {
      setHandlers(list);
      setHandlerId(list[0]?.handler_id ?? "");
    });
  }, []);

  const payout = claim.decision?.payout ?? 0;

  const submit = () => {
    api
      .signOff(claim.claim_id, handlerId)
      .then(onSigned)
      .catch(() => {
        setError("The sign-off did not go through. Please try again.");
      });
  };

  return (
    <section className="panel signoff">
      <h2>Sign-off needed</h2>
      <p>
        The agent approved a payout of {money(payout)}, which is over the
        $1,000.00 limit. The payment waits until a handler signs off.
      </p>
      <div className="signoff-form">
        <label>
          Handler{" "}
          <select
            value={handlerId}
            onChange={(e) => {
              setHandlerId(e.target.value);
            }}
          >
            {handlers.map((h) => (
              <option key={h.handler_id} value={h.handler_id}>
                {h.name}, {h.role}
              </option>
            ))}
          </select>
        </label>
        <button type="button" disabled={!handlerId} onClick={submit}>
          Sign off and pay {money(payout)}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
