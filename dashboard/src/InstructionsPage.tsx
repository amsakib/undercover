import { useEffect, useState } from "react";
import { api, type InstructionsName } from "./api";

const TITLES: Record<InstructionsName, string> = {
  queue: "Running the queue",
  claim: "Working a claim",
};

function Instructions({ name }: Readonly<{ name: InstructionsName }>) {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    void api.instructions(name).then((result) => {
      setText(result.text);
    });
  }, [name]);

  return (
    <section className="panel">
      <h2>{TITLES[name]}</h2>
      {text === null ? (
        <p className="muted">Loading the instructions.</p>
      ) : (
        <pre className="instructions">{text}</pre>
      )}
    </section>
  );
}

export function InstructionsPage() {
  return (
    <>
      <div className="page-head">
        <h1>Agent instructions</h1>
        <span className="muted">Read only</span>
      </div>
      <Instructions name="queue" />
      <Instructions name="claim" />
    </>
  );
}
