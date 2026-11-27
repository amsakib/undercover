import type { Run } from "./api";
import { TodoChip } from "./Chip";

export function RunPanel({ run }: Readonly<{ run: Run }>) {
  const done = run.todos.filter((t) => t.status !== "todo").length;
  return (
    <section className="panel" aria-label="Current run">
      <div className="panel-head">
        <h2>{run.status === "running" ? "Current run" : "Last run"}</h2>
        <p className="muted">
          Up to {run.claim_limit} claims ·{" "}
          {run.status === "running" ? "Working" : "Finished"}
        </p>
      </div>
      {run.todos.length === 0 ? (
        <p className="muted">The agent is planning the run.</p>
      ) : (
        <>
          <p className="muted">
            {done} of {run.todos.length} to-dos started or done
          </p>
          <ol className="todos">
            {run.todos.map((todo, i) => (
              <li key={`${String(i)}-${todo.text}`}>
                <TodoChip status={todo.status} />
                {todo.claim_id ? (
                  <a href={`#/claims/${todo.claim_id}`}>{todo.text}</a>
                ) : (
                  <span>{todo.text}</span>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
      {run.summary && <p className="summary">{run.summary}</p>}
    </section>
  );
}
