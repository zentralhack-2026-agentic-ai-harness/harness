"""What the container runs: `harness`, with no arguments (see the README's contract).

This file only connects the fixed paths to the agent; how the agent works (model, prompt,
tools, budget) is in agent.py.
"""

import json
from pathlib import Path

from harness.agent import run_agent

TASK = Path("/task")  # spec.md and task.json, read-only
OUTPUT = Path("/output")  # write task["strategy_file"] here; logs welcome
WORK = Path("/tmp/work")  # the agent's working directory (/tmp is the only other writable place)


def main() -> None:
    spec = (TASK / "spec.md").read_text()
    task = json.loads((TASK / "task.json").read_text())
    for d in (OUTPUT / "logs", WORK):
        d.mkdir(parents=True, exist_ok=True)

    strategy_path = OUTPUT / task["strategy_file"]
    run_agent(
        spec=spec,
        task=task,
        strategy_path=strategy_path,
        work_dir=WORK,
        log_path=OUTPUT / "logs" / "transcript.jsonl",
    )
    print(f"strategy {'written' if strategy_path.exists() else 'MISSING'}: {strategy_path}")


if __name__ == "__main__":
    main()
