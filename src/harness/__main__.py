"""The entry point: `harness`.

With no arguments it is what the container runs (see the README's contract): the task is in
/task, the strategy goes to /output. `harness TASK_DIR` runs the same agent directly on your
machine, without Docker, into runs/<task>/<time>/ (like run.sh): quicker to iterate on, and
you can step through it with a debugger.

This file only connects the paths to the agent; how the agent works (model, prompt, tools,
budget) is in agent.py.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from harness.agent import run_agent


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="harness", description="Without TASK_DIR: the container's /task and /output."
    )
    parser.add_argument(
        "task_dir", nargs="?", type=Path, help="run locally on this task (from arena make-task)"
    )
    args = parser.parse_args()
    if args.task_dir is None:
        # The container: /task is read-only, /output and /tmp are the only writable places.
        run(Path("/task"), Path("/output"), Path("/tmp/work"))
    else:
        task_dir = args.task_dir
        if not (task_dir / "spec.md").is_file() or not (task_dir / "task.json").is_file():
            parser.error(f"{task_dir}: no spec.md/task.json")
        # Absolute: the agent's bash commands run in the work directory, not here.
        run_dir = Path("runs").resolve() / task_dir.resolve().name
        run_dir /= datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir.mkdir(parents=True)
        latest = run_dir.parent / "latest"  # runs/<task>/latest: the newest run
        latest.unlink(missing_ok=True)
        latest.symlink_to(run_dir.name)
        print(f"running {task_dir} into {run_dir} (no Docker, no deadline)", flush=True)
        run(task_dir, run_dir / "output", run_dir / "work")


def run(task_dir: Path, output: Path, work: Path) -> None:
    spec = (task_dir / "spec.md").read_text()
    task = json.loads((task_dir / "task.json").read_text())
    for d in (output / "logs", work):
        d.mkdir(parents=True, exist_ok=True)

    strategy_path = output / task["strategy_file"]
    run_agent(
        spec=spec,
        task=task,
        strategy_path=strategy_path,
        work_dir=work,
        log_path=output / "logs" / "transcript.jsonl",
    )
    print(f"strategy {'written' if strategy_path.exists() else 'MISSING'}: {strategy_path}")


if __name__ == "__main__":
    main()
