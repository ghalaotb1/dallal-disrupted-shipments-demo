"""`dallal-agent`: run the agent on a synthetic scenario or a fixture file and print/write the audit trace."""

from __future__ import annotations

import argparse
import json
import logging

from dallal.agent.frontend import to_frontend
from dallal.agent.runtime import AgentRuntime
from dallal.data.augment.scenarios import SCENARIOS
from dallal.tools.bundle import Bundle


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dallal-agent")
    ap.add_argument("scenario", help=f"one of {sorted(SCENARIOS)} or a path to a fixture .json")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--llm", action="store_true", help="use the Anthropic tool-use planner (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--frontend", action="store_true", help="print the UI-compatible AgentRun JSON instead of the audit trace")
    ap.add_argument("--out", help="write the trace JSON here")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    bundle = SCENARIOS[args.scenario](args.seed) if args.scenario in SCENARIOS else Bundle.from_json(args.scenario)
    planner = None
    if args.llm:
        from dallal.agent.llm import LLMPlanner

        planner = LLMPlanner()
    run, _ = AgentRuntime(planner=planner).investigate(bundle)
    if args.out:
        run.write(__import__("pathlib").Path(args.out))
    print(json.dumps(to_frontend(run) if args.frontend else run.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
