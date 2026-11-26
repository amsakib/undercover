import { useEffect, useState } from "react";
import { api } from "./api";

export function InstructionsPage() {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    void api.instructions().then((result) => {
      setText(result.text);
    });
  }, []);

  return (
    <section className="panel">
      <div className="panel-head">
        <h1>Agent instructions</h1>
        <span className="muted">Read only</span>
      </div>
      {text === null ? (
        <p className="muted">Loading the instructions.</p>
      ) : (
        <pre className="instructions">{text}</pre>
      )}
    </section>
  );
}
