# harness

The starting point for your Zentral Hack 2026 harness. Create your own repository from this
template (**Use this template** on GitHub) and make it better.

It is deliberately minimal: one model (always the cheapest allowed one), one tool (`bash`) and
a loop that stops when the model answers without calling the tool. It reads a game's `spec.md`
and asks the model to write a strategy. It has no budget management, no retries, no fallback
strategy, no conformance check, no simulator. Building those (or something better) is the hackathon.

```
src/harness/
  __main__.py  # the `harness` command: connects the task and output paths to the agent
  agent.py     # the agent: model choice, settings, the loop (Responses API), the bash tool
  pricing.py   # what a call costs, as the evaluation counts it
  prompt.md    # the system prompt
run.sh         # run it on a task locally, the way the evaluation does
Dockerfile     # the sandbox your harness runs in at evaluation time
.vscode/launch.json  # run or debug it without Docker in VS Code
```

## The contract

At evaluation time your harness runs unattended, on a game it has never seen. Three things are
fixed; everything else in this repository is yours to change.

1. **The build.** We build your repository at the freeze commit with **our** copy of the
   `Dockerfile`, which runs `uv sync --frozen` on your `pyproject.toml` and `uv.lock`.
2. **The run.** We start the container, which runs the `harness` script your `pyproject.toml`
   defines (`[project.scripts]`), **with no arguments**, as an unprivileged user, with:

   | path              | what                                                                    |
   |-------------------|-------------------------------------------------------------------------|
   | `/task/spec.md`   | the game's complete written specification (read-only)                  |
   | `/task/task.json` | `strategy_file`, `strategy_class`, budget, deadline, allowed models, prices |
   | `/output/`        | write `<strategy_file>` here, defining `<strategy_class>`; logs welcome |
   | `/tmp/`           | scratch space (tmpfs, 1 GB)                                             |

   Nothing else is writable: not the root file system, not your code or its virtualenv. There
   are CPU, memory and process limits (2 CPUs, 4 GB of RAM, no swap).
3. **The result.** When the harness exits, or at `deadline_s` (wall clock from container
   start), we take `/output/<strategy_file>`. At the deadline your harness gets SIGTERM, and
   SIGKILL 30 seconds later (Python exits on SIGTERM by default: install a handler to use those
   30 seconds). So write a fallback strategy early and improve it.

`./run.sh` does exactly this on your machine (see [Run it locally](#run-it-locally)).

More about what goes in and out:

- After the run, only `<strategy_file>` is copied into the tournament, on its own: it must not
  import other files from `/output`.
- The strategy is a single Python file: standard library only, a class with
  `__init__(self, player_id)` and `act(self, obs)`. It does not need to import anything from us.
- LLM access: the OpenAI Responses API only (see [Models and budget](#models-and-budget)). The
  container has no other network access: no PyPI, no web.
- The evaluation builds the image with **its own copy** of the `Dockerfile`. Add Python
  dependencies through `pyproject.toml` / `uv.lock` (`uv add ...`); other changes to the
  `Dockerfile` have no effect at evaluation time.

## Models and budget

`task.json` gives the `allowed_models`, their `prices` and a `budget_usd`. **At evaluation both
are enforced**: other models are refused, and once the budget is spent every further call
fails (spending past it is recorded and may be penalised). **During development nothing
enforces them**, so develop as if it did: keep to the allowed models and track your spend.
`harness.pricing.cost(response.usage, task["prices"][model])` gives what a call costs; the
template's loop already adds it up and prints it.

Use the openai SDK as the template does: `OpenAI()` reads the key and endpoint from the
environment (your own key in development, one for the run at evaluation), so the same code
works in both. Only the Responses API with function tools is available: no hosted tools (web
search, code interpreter, ...), no stored responses (`previous_response_id`), at most 4 calls
at a time.

## Run it locally

You need git, Docker, [uv](https://docs.astral.sh/uv/) and an OpenAI key. Everything runs from
your clone of this repository: `uv sync` also installs, for development only,
[arena](https://github.com/zentralhack-2026-agentic-ai-harness/arena) (the `arena` command and
the strategy contract) and
[arena-games-dev](https://github.com/zentralhack-2026-agentic-ai-harness/arena-games-dev) (the
dev games: spec, simulator and baselines). Read their code on GitHub; you do not need to clone
them.

```bash
git clone <your repository> harness
cd harness
uv sync

# 1. your key, for the harness (gitignored)
echo "OPENAI_API_KEY=sk-..." > .env

# 2. a task for the dev game alpha: exactly what the harness gets as /task
uv run arena make-task --game arena_games_dev.alpha --budget-usd 1 --deadline-s 600 \
    --model gpt-6-luna --model gpt-6.1-sol --out tasks/alpha

# 3. run the harness on it, as the evaluation does
./run.sh tasks/alpha
```

`run.sh` builds the image and runs it with the evaluation's mounts, limits and deadline. Only
the budget is not enforced (see above). Each run gets its own directory; the newest is
`runs/alpha/latest/`, with the strategy and transcript in `output/` and the container's output
in `harness.log`.

Then check the strategy and play it against the game's baselines:

```bash
uv run arena check runs/alpha/latest/output/strategy.py:Strategy --game arena_games_dev.alpha
uv run arena run --game arena_games_dev.alpha \
    --strategies mine=runs/alpha/latest/output/strategy.py:Strategy \
    --panel arena_games_dev.alpha.baselines:DoNothing \
            arena_games_dev.alpha.baselines:RandomStrategy \
            arena_games_dev.alpha.baselines:ProportionalSpread \
    --seeds 10 --workers 8
```

Both options take any `[name=]path/to/file.py:Class` or `package.module:Class`. Without
`--panel`, the `--strategies` play each other, so you can compare any strategies, e.g. two runs
of your harness. The other dev games work the same way (see `arena-games-dev`'s README).

### Without Docker, and in the debugger

For quicker iterations, run the same agent directly on your machine:

```bash
uv run --env-file .env harness tasks/alpha
```

It writes into `runs/alpha/<time>/` like `run.sh` (so the commands above work on it too), with
`output/` and the agent's working directory `work/`; the log goes to your terminal. To step
through it, open this repository in VS Code (with the Python extension), set breakpoints, and
start **harness (local)** in Run and Debug (F5); it asks for the task directory.

This is not the evaluation's environment, so check with `run.sh` before you rely on it:

- **The model's bash commands run on your machine, as you**, with no container around them:
  they can read and change anything you can. Watch what it does.
- No deadline, no CPU or memory limits, and your machine's tools rather than the image's.
  `python3` is your system's, not the harness's virtualenv (which has arena and the dev games
  installed; the container has neither).

### Updating arena and the dev games

When we announce a fix to arena or arena-games-dev, run this in your repository:

```bash
uv sync --upgrade-package arena --upgrade-package arena-games-dev
```

It moves both to their latest `main` and records the new commits in `uv.lock`; commit that
change. Neither is part of the evaluation image (it installs without the dev dependencies), so
this only affects your local runs. You can also read the installed code offline in
`.venv/lib/python3.13/site-packages/arena/` and `.../arena_games_dev/`.

## Settings

The evaluation runs `harness` without arguments (`harness TASK_DIR` is only for local runs, see
above), so there are no command-line options. The settings are constants at the top of
`src/harness/agent.py`: `REASONING_EFFORT` (`medium`), `MAX_STEPS` (30) and the
bash tool's limits. The model is chosen there too (`cheapest_model`): always the cheapest of
the task's `allowed_models`, by input plus output price in `task.json`'s `prices`. Every model
response, its token usage, the spend so far and the tool results are appended to
`logs/transcript.jsonl` in the output directory.
