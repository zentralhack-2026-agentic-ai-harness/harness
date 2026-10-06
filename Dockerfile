# The adapt sandbox. The evaluation builds your repo with ITS copy of this file, so changes
# here have no effect at evaluation time: add Python dependencies via pyproject.toml/uv.lock.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1
WORKDIR /harness
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev

RUN useradd --create-home agent && mkdir /task /output /work && chown agent /output /work
USER agent

# Contract: /task (read-only) holds spec.md and task.json; write output/<strategy_file>.
ENTRYPOINT ["/harness/.venv/bin/harness"]
CMD ["--task", "/task", "--output", "/output", "--work", "/work"]
