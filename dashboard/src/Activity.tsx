import type { Step } from "./api";

const KIND_LABELS: Record<Step["kind"], string> = {
  message: "Agent",
  tool_call: "Tool call",
  tool_result: "Result",
};

function time(at: string): string {
  return new Date(at).toLocaleTimeString("en-US", { hour12: false });
}

function StepText({ step }: Readonly<{ step: Step }>) {
  if (step.kind === "message") return <p>{step.text}</p>;
  if (step.kind === "tool_call") return <p className="mono">{step.text}</p>;
  const [name = "", ...rest] = step.text.split(": ");
  return (
    <details>
      <summary className="mono">{name}</summary>
      <p className="mono result">{rest.join(": ")}</p>
    </details>
  );
}

export function Activity({
  steps,
  working,
}: Readonly<{ steps: Step[]; working: boolean }>) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Agent activity</h2>
        {working && <span className="muted">Working</span>}
      </div>
      {steps.length === 0 ? (
        <p className="muted">The agent has not worked on this claim yet.</p>
      ) : (
        <ol className="steps">
          {steps.map((step) => (
            <li key={step.step_id} className={`step step-${step.kind}`}>
              <span className="step-meta">
                <span className="mono">{time(step.at)}</span>{" "}
                {KIND_LABELS[step.kind]}
              </span>
              <StepText step={step} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
