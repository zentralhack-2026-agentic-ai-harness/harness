"""The agent loop: one model, one tool (bash), until the model stops calling it."""

import json
import os
import signal
import subprocess
from pathlib import Path

from openai import OpenAI

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

COMMAND_TIMEOUT_S = 60
MAX_OUTPUT_CHARS = 10_000


def run_agent(
    *,
    instructions: str,
    task_prompt: str,
    work_dir: Path,
    log_path: Path,
    model: str,
    reasoning_effort: str,
    max_steps: int,
) -> None:
    client = OpenAI()  # reads OPENAI_API_KEY and OPENAI_BASE_URL
    # The whole conversation lives here (store=False), so no server-side state is needed.
    conversation: list[dict] = [{"role": "user", "content": task_prompt}]

    with log_path.open("a") as log:
        for step in range(max_steps):
            response = client.responses.create(
                model=model,
                instructions=instructions,
                input=conversation,
                tools=[BASH_TOOL],
                reasoning={"effort": reasoning_effort},
                store=False,
                include=["reasoning.encrypted_content"],  # carry reasoning across turns
            )
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
                        "output": output,
                        "tool_results": results,
                    }
                )
                + "\n"
            )
            log.flush()
            print(f"step {step}: {_describe(output)}", flush=True)

            if not calls:
                return  # the model answered without a tool call: it is done
    print(f"stopped after max_steps={max_steps}", flush=True)


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
