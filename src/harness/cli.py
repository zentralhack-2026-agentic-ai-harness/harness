import argparse
import json
import os
from pathlib import Path

from harness.agent import run_agent

PROMPT = Path(__file__).with_name("prompt.md")


def main() -> None:
    parser = argparse.ArgumentParser(prog="harness")
    parser.add_argument("--task", type=Path, default=Path("/task"), help="spec.md + task.json")
    parser.add_argument("--output", type=Path, default=Path("/output"), help="strategy + logs")
    parser.add_argument("--work", type=Path, default=Path("/work"), help="scratch directory")
    parser.add_argument("--model", default=os.environ.get("HARNESS_MODEL", "gpt-6-luna"))
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--max-steps", type=int, default=30)
    args = parser.parse_args()

    spec = (args.task / "spec.md").read_text()
    task = json.loads((args.task / "task.json").read_text())
    for d in (args.output, args.output / "logs", args.work):
        d.mkdir(parents=True, exist_ok=True)

    strategy_path = (args.output / task["strategy_file"]).resolve()
    instructions = PROMPT.read_text().format(
        work_dir=args.work.resolve(),
        strategy_path=strategy_path,
        strategy_class=task["strategy_class"],
    )
    task_prompt = f"task.json:\n```json\n{json.dumps(task, indent=2)}\n```\n\n{spec}"

    run_agent(
        instructions=instructions,
        task_prompt=task_prompt,
        work_dir=args.work.resolve(),
        log_path=args.output / "logs" / "transcript.jsonl",
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        max_steps=args.max_steps,
    )
    print(f"strategy {'written' if strategy_path.exists() else 'MISSING'}: {strategy_path}")
