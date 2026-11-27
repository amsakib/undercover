import type { Status, Todo } from "./api";

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

export function money(amount: number): string {
  return usd.format(amount);
}

export function label(value: string): string {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const STATUS_LABELS: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  awaiting_signoff: "Waiting for sign-off",
  decided: "Decided",
  needs_handler: "Left for a handler",
};

export const TODO_LABELS: Record<Todo["status"], string> = {
  todo: "To do",
  in_progress: "In progress",
  done: "Done",
  handler: "Left for a handler",
};
