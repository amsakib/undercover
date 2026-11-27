"""Work the claims queue.

`uv run -m agent` works the whole queue, `uv run -m agent --limit 5` caps the run
at five claims, and `uv run -m agent CLM-1001` works one claim.
"""

import argparse
import sys

from agent import main
from agent.queue_agent import claims, run_queue


def work_one(claim_id: str) -> None:
    """Work one claim, trying it a second time if it fails once."""
    try:
        line = main.work_claim(claim_id)
        print(line)
        if main.get(f"/api/claims/{claim_id}")["status"] == "waiting":
            print(main.work_claim(claim_id))
    except main.RateLimitStop as stop:
        print(stop)


def parse(argv: list[str]) -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(prog="uv run -m agent")
    parser.add_argument("claim_id", nargs="?", help="work only this claim")
    parser.add_argument("--limit", type=int, help="start at most this many claims")
    return parser.parse_args(argv)


def cli(argv: list[str]) -> None:
    """Work one claim, or run the queue with an optional cap."""
    args = parse(argv)
    if args.claim_id:
        work_one(args.claim_id)
        return
    run = run_queue(args.limit or len(claims()))
    print(run["summary"])


if __name__ == "__main__":
    cli(sys.argv[1:])
