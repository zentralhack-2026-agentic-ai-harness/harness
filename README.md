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
| `/work/`          | scratch space (tmpfs)                                                  |
| `/tmp/`           | scratch space (tmpfs)                                                  |
| `/output/`        | write `<strategy_file>` here, defining `<strategy_class>`; logs welcome |

- The command is the image's entry point: `harness --task /task --output /output --work /work`.
  Keep it working.
- Everything else is read-only: the root file system, your code and its virtualenv. There are
  CPU, memory and process limits (currently 2 CPUs and 4 GB of RAM, no swap).
- `deadline_s` is wall clock, from container start. At the deadline your harness gets SIGTERM,
  and SIGKILL 30 seconds later (Python exits on SIGTERM by default: install a handler to use
  those 30 seconds). Whatever `/output/<strategy_file>` holds at that point is what
  gets evaluated, so write a fallback strategy early and improve it.
- After the run, only `<strategy_file>` is copied into the tournament, on its own: it must not
  import other files from `/output`.
- The strategy is a single Python file: standard library only, a class with
  `__init__(self, player_id)` and `act(self, obs)`. It does not need to import anything from us.
- LLM access: the OpenAI **Responses API** (`client.responses.create`) through the evaluation's
  gateway, with `OPENAI_BASE_URL` and `OPENAI_API_KEY` set for you (see
  [LLM access and budget](#llm-access-and-budget)). The container has no other network access:
  no PyPI, no web.
- The evaluation builds the image with **its own copy** of the `Dockerfile`. Add Python
  dependencies through `pyproject.toml` / `uv.lock` (`uv add ...`); other changes to the
  `Dockerfile` have no effect at evaluation time.

## LLM access and budget

**During development** you use your team's own OpenAI key, which has the hackathon's model
allow-list and your team's spend limit. Call OpenAI directly with the openai SDK, as the
template does.

**At evaluation** your harness gets a fresh key (a token for that run only) and
`OPENAI_BASE_URL`, pointing at our gateway. The openai SDK picks both up from the environment
(`OpenAI()`), so the same code works in both places. The gateway enforces the task's
`task.json`:

- `allowed_models`: any other model is refused (400 `model_not_allowed`).
- `budget_usd`: every call is charged by the formula below. Calls go through while your
  spend is below the budget, so the call that crosses it still completes. After that, every
  call gets **429 `budget_exhausted`** (type `insufficient_quota`). The SDK does not retry it;
  it raises `openai.RateLimitError` with `e.code == "budget_exhausted"`. Spending past the
  budget is recorded and may be penalised, so stop before you reach it.
- Use the Responses API only (`POST /v1/responses`), with function (or custom) tools. Refused:
  hosted tools (web search, file search, code interpreter, ...), `background`, a
  `service_tier` other than the default, and `previous_response_id` / `conversation` /
  `prompt` (responses are not stored: send the full input each time).
- At most 4 calls at a time. More get a 429 that the SDK retries.

**The cost of a call**, in USD, with `task["prices"][model]` (USD per 1M tokens, OpenAI's
Standard tier):

```
cost = (uncached × input + cached × cached_input + cache_write × cache_write + output × output) / 1e6
```

- `cached` and `cache_write` are `usage.input_tokens_details.cached_tokens` and
  `.cache_write_tokens`; `uncached` is the rest of `usage.input_tokens`.
- `output` is `usage.output_tokens`, reasoning tokens included.
- A call whose input is above the model's `long_context.above_input_tokens` (272K) is charged
  **entirely** at its `long_context` prices.

The same function is `arena.pricing.cost` in
[`arena`](https://github.com/zentralhack-2026-agentic-ai-harness/arena). Your harness does not
depend on arena, so copy the formula: it is a few lines. Add up `cost(response.usage, ...)`
after every call and you know exactly what the gateway counts.

## Run it locally

Requires [uv](https://docs.astral.sh/uv/). Put your key in a `.env` file (`OPENAI_API_KEY=...`;
it is gitignored).

Get a task directory for a dev game with the `arena` CLI from
[`arena-games-dev`](https://github.com/zentralhack-2026-agentic-ai-harness/arena-games-dev),
cloned next to this repo (the commands below assume this repo's directory is `harness`):

```bash
cd ../arena-games-dev
uv run arena make-task --game arena_games_dev.alpha --out ../harness/tasks/alpha
```

Run the harness directly:

```bash
uv run --env-file .env harness --task tasks/alpha --output runs/alpha/output --work runs/alpha/work
```

Or in the sandbox, as the evaluation does:

```bash
docker build -t harness .
mkdir -p runs/alpha/output
docker run --rm --init --env-file .env --user "$(id -u):$(id -g)" \
    --read-only --tmpfs /work --tmpfs /tmp \
    -v "$PWD/tasks/alpha:/task:ro" -v "$PWD/runs/alpha/output:/output" \
    harness
```

(With rootless Docker use `--user 0:0` instead: container root is your own user there.)

Then check and score the strategy, from `arena-games-dev`:

```bash
uv run arena check ../harness/runs/alpha/output/strategy.py:Strategy \
    --game arena_games_dev.alpha
uv run arena run --game arena_games_dev.alpha \
    --strategies mine=../harness/runs/alpha/output/strategy.py:Strategy \
    --panel arena_games_dev.alpha.baselines:DoNothing \
            arena_games_dev.alpha.baselines:RandomStrategy \
            arena_games_dev.alpha.baselines:ProportionalSpread \
    --seeds 10 --workers 8
```

## Options

`harness --help`: `--model` (default `gpt-6-luna`, or `$HARNESS_MODEL`), `--reasoning-effort`
(default `medium`), `--max-steps` (default 30). Every model response, its token usage and the
tool results are appended to `<output>/logs/transcript.jsonl`.

## Rules of thumb

- Your harness never gets game source code or a simulator, during development or evaluation:
  only `spec.md`. You may read the dev games' source yourself; the evaluation games are
  different.
- The bash tool does not pass `OPENAI_*` variables to commands, but it runs as the same user as
  the harness. Do not rely on it as a security boundary.
