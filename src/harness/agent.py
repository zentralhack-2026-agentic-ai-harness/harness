"""The agent: one model (the cheapest allowed), one tool (bash), a loop until the model stops
calling it."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from openai import OpenAI

from harness.pricing import cost

BASH_TOOL = {
    "type": "function",
    "name": "bash",
    "description": (
        "Run a bash command in the working directory and return its exit code, stdout and "
        "stderr. Each call starts a fresh shell; files persist between calls."
    ),
    "parameters": {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "the command to run"}},
        "required": ["command"],
        "additionalProperties": False,
    },
    "strict": True,
}

REASONING_EFFORT = "medium"
MAX_STEPS = 30
COMMAND_TIMEOUT_S = 60
MAX_OUTPUT_CHARS = 10_000
PROMPT = Path(__file__).with_name("prompt.md")


def cheapest_model(task: dict) -> str:
    """The allowed model with the lowest input + output price per token (ties: by name)."""
    prices = task["prices"]
    allowed = task.get("allowed_models") or list(prices)
    return min(allowed, key=lambda m: (prices[m]["input"] + prices[m]["output"], m))


def run_agent(
    *, spec: str, task: dict, strategy_path: Path, work_dir: Path, log_path: Path
) -> None:
    """Have the model write `strategy_path` for the game in `spec`, working in `work_dir`."""
    model = cheapest_model(task)
    price = task["prices"][model]
    print(f"model: {model}", flush=True)
    instructions = PROMPT.read_text().format(
        work_dir=work_dir,
        strategy_path=strategy_path,
        strategy_class=task["strategy_class"],
    )
    task_prompt = f"task.json:\n```json\n{json.dumps(task, indent=2)}\n```\n\n{spec}"

    client = OpenAI()  # reads OPENAI_API_KEY and OPENAI_BASE_URL
    # The whole conversation lives here (store=False), so no server-side state is needed.
    conversation: list[dict] = [{"role": "user", "content": task_prompt}]
    spent = 0.0  # USD, as the gateway counts it

    with log_path.open("a") as log:
        for step in range(MAX_STEPS):
            response = client.responses.create(
                model=model,
                instructions=instructions,
                input=conversation,
                tools=[BASH_TOOL],
                reasoning={"effort": REASONING_EFFORT},
                store=False,
                include=["reasoning.encrypted_content"],  # carry reasoning across turns
            )
            spent += cost(response.usage, price)
            output = [item.model_dump(exclude_none=True) for item in response.output]
            conversation += output

            calls = [item for item in output if item["type"] == "function_call"]
            results = []
            for call in calls:
                result = _run_tool(call, work_dir)
                results.append(result)
                conversation.append(
                    {"type": "function_call_output", "call_id": call["call_id"], "output": result}
                )

            log.write(
                json.dumps(
                    {
                        "step": step,
                        "model": model,
                        "usage": response.usage.model_dump() if response.usage else None,
                        "spent_usd": spent,
                        "output": output,
                        "tool_results": results,
                    }
                )
                + "\n"
            )
            log.flush()
            print(f"step {step} (${spent:.4f}): {_describe(output)}", flush=True)

            if not calls:
                return  # the model answered without a tool call: it is done
    print(f"stopped after MAX_STEPS={MAX_STEPS}", flush=True)


def _run_tool(call: dict, work_dir: Path) -> str:
    if call["name"] != "bash":
        return f"error: unknown tool {call['name']!r}"
    try:
        command = json.loads(call["arguments"])["command"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return f"error: arguments must be JSON with a 'command' string, got {call['arguments']!r}"
    return bash(command, work_dir)


def bash(command: str, cwd: Path, timeout: float = COMMAND_TIMEOUT_S) -> str:
    """Run `command` with bash; the API key is not passed on."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENAI_")}
    # Local runs (uv run, the debugger) put the harness's virtualenv first on PATH; the
    # container does not. Drop it, so that python3 is the plain interpreter in both.
    venv_bin = str(Path(sys.executable).parent)
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p != venv_bin)
    env.pop("VIRTUAL_ENV", None)
    proc = subprocess.Popen(
        ["bash", "-c", command],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=True,  # so a timeout also kills background jobs
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        status = f"exit code: {proc.returncode}"
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        status = f"timed out after {timeout:.0f}s and was killed"
    return f"{status}\n--- stdout ---\n{_clip(stdout)}\n--- stderr ---\n{_clip(stderr)}"


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return f"{text[:half]}\n[... {len(text) - MAX_OUTPUT_CHARS} chars cut ...]\n{text[-half:]}"


def _describe(output: list[dict]) -> str:
    parts = []
    for item in output:
        if item["type"] == "function_call":
            parts.append(f"bash {json.loads(item['arguments']).get('command', '')[:80]!r}")
        elif item["type"] == "message":
            parts.append("message")
    return ", ".join(parts) or "(reasoning only)"
