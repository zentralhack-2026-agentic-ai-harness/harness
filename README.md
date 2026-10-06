# harness-template

The starting point for your Zentral Hack 2026 harness. Fork it and make it better.

It is deliberately minimal: one model, one tool (`bash`) and a loop that stops when the model
answers without calling the tool. It reads a game's `spec.md` and asks the model to write a
strategy. It has no budget management, no retries, no fallback strategy, no conformance check,
no simulator. Building those (or something better) is the hackathon.

```
src/harness/
  cli.py      # entry point: reads /task, sets up /output and /work, runs the agent
  agent.py    # the loop (OpenAI Responses API) and the bash tool
  prompt.md   # the system prompt
Dockerfile    # the sandbox your harness runs in at evaluation time
```

## The contract

At evaluation time your harness runs unattended in a container built from this repo at your
freeze commit, on a game it has never seen:

| path              | what                                                                   |
|-------------------|------------------------------------------------------------------------|
| `/task/spec.md`   | the game's complete written specification (read-only)                 |
| `/task/task.json` | `strategy_file`, `strategy_class`, budget, deadline, allowed models    |
| `/work/`          | scratch space                                                          |
| `/output/`        | write `<strategy_file>` here, defining `<strategy_class>`; logs welcome |

- The command is the image's entry point: `harness --task /task --output /output --work /work`.
  Keep it working.
- The strategy is a single Python file: standard library only, a class with
  `__init__(self, player_id)` and `act(self, obs)`. It does not need to import anything from us.
- LLM access goes through `OPENAI_API_KEY` and, later, `OPENAI_BASE_URL` (the metered gateway).
  Use the OpenAI **Responses API** (`client.responses.create`): on the allowed models, function
  tools with reasoning are not supported on chat completions.
- The evaluation builds the image with **its own copy** of the `Dockerfile`. Add Python
  dependencies through `pyproject.toml` / `uv.lock` (`uv add ...`); other changes to the
  `Dockerfile` have no effect at evaluation time.

## Run it locally

Requires [uv](https://docs.astral.sh/uv/). Put your key in a `.env` file (`OPENAI_API_KEY=...`;
it is gitignored).

Get a task directory for a dev game with the `arena` CLI from
[`arena-games-dev`](https://github.com/zentralhack-2026-agentic-ai-harness/arena-games-dev):

```bash
cd ../arena-games-dev
uv run arena make-task --game arena_games_dev.alpha --out ../harness-template/tasks/alpha
```

Run the harness directly:

```bash
uv run --env-file .env harness --task tasks/alpha --output runs/alpha/output --work runs/alpha/work
```

Or in the sandbox, as the evaluation does:

```bash
docker build -t harness .
mkdir -p runs/alpha/output
docker run --rm --env-file .env --user "$(id -u):$(id -g)" \
    -v "$PWD/tasks/alpha:/task:ro" -v "$PWD/runs/alpha/output:/output" --tmpfs /work \
    harness
```

(With rootless Docker use `--user 0:0` instead: container root is your own user there.)

Then check and score the strategy, from `arena-games-dev`:

```bash
uv run arena check ../harness-template/runs/alpha/output/strategy.py:Strategy \
    --game arena_games_dev.alpha
uv run arena run --game arena_games_dev.alpha \
    --strategies mine=../harness-template/runs/alpha/output/strategy.py:Strategy \
    --panel arena_games_dev.alpha.baselines:DoNothing \
            arena_games_dev.alpha.baselines:RandomStrategy \
            arena_games_dev.alpha.baselines:ProportionalSpread \
    --seeds 10 --workers 8
```

## Options

`harness --help`: `--model` (default `gpt-5.6-luna`, or `$HARNESS_MODEL`), `--reasoning-effort`
(default `medium`), `--max-steps` (default 30). Every model response, its token usage and the
tool results are appended to `<output>/logs/transcript.jsonl`.

## Rules of thumb

- Your harness never gets game source code or a simulator, during development or evaluation:
  only `spec.md`. You may read the dev games' source yourself; the evaluation games are
  different.
- The bash tool does not pass `OPENAI_*` variables to commands, but it runs as the same user as
  the harness. Do not rely on it as a security boundary.
