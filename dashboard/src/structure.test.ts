import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

it("calls the backend only from api.ts", () => {
  const dir = import.meta.dirname;
  const sources = readdirSync(dir).filter(
    (name) =>
      /\.tsx?$/.test(name) && !name.includes(".test.") && name !== "api.ts",
  );
  expect(sources).toContain("QueuePage.tsx");
  for (const name of sources) {
    const text = readFileSync(join(dir, name), "utf-8");
    expect(text, name).not.toMatch(/fetch\(|["`]\/api\//);
  }
});
