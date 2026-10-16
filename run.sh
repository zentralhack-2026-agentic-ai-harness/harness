#!/usr/bin/env bash
# Run the harness on a task the way the evaluation does: same image, same limits, same
# deadline. The one difference: LLM calls go straight to OpenAI with the key in .env, not
# through the evaluation's gateway, so nothing refuses a call once the budget is spent.
#
#   ./run.sh tasks/alpha
#
# Each run gets a fresh directory runs/<task>/<time>/ (runs/<task>/latest points to it) holding
# output/ (what /output held at the end: the strategy and logs/) and harness.log (the
# container's stdout and stderr).
set -euo pipefail
cd "$(dirname "$0")"

task=${1:?usage: ./run.sh TASK_DIR (made with arena make-task, see the README)}
[[ -f $task/spec.md && -f $task/task.json ]] || { echo "$task: no spec.md/task.json" >&2; exit 2; }
[[ -f .env ]] || { echo ".env missing: put OPENAI_API_KEY=... in it" >&2; exit 2; }
field() {  # field NAME: a task.json value, empty if it is null
    python3 -c 'import json, sys; v = json.load(open(sys.argv[1]))[sys.argv[2]]; print("" if v is None else v)' \
        "$task/task.json" "$1"
}
deadline=$(field deadline_s)  # null in tasks made without --deadline-s: no deadline then
deadline=${deadline%.*}

run=runs/$(basename "$(realpath "$task")")/$(date +%Y%m%d-%H%M%S)
mkdir -p "$run/output"
ln -sfn "$(basename "$run")" "$(dirname "$run")/latest"  # runs/<task>/latest: the newest run

docker build --quiet --tag harness . >/dev/null

# Container root is your own user on rootless Docker; elsewhere run as you, so the files are yours.
if docker info --format '{{json .SecurityOptions}}' | grep -q rootless; then
    user=0:0
else
    user="$(id -u):$(id -g)"
fi

name=harness-$$
trap 'docker rm --force "$name" >/dev/null 2>&1 || true' EXIT
echo "running $task, deadline ${deadline:-none}${deadline:+s}, into $run"
docker run --detach --name "$name" --init --env-file .env --user "$user" \
    --cpus 2 --memory 4g --memory-swap 4g --pids-limit 512 \
    --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:size=1g \
    --volume "$(realpath "$task"):/task:ro" --volume "$(realpath "$run/output"):/output:rw" \
    harness >/dev/null
docker logs --follow "$name" 2>&1 | tee "$run/harness.log" &

# The deadline, from container start: SIGTERM, then SIGKILL 30 seconds later (docker stop).
end=$((SECONDS + ${deadline:-0}))
while [[ $(docker inspect --format '{{.State.Running}}' "$name") == true ]]; do
    if [[ -n $deadline ]] && ((SECONDS >= end)); then
        echo "deadline: SIGTERM, SIGKILL in 30 s"
        docker stop --timeout 30 "$name" >/dev/null
        break
    fi
    sleep 1
done
wait
strategy=$(field strategy_file)
echo "exit code $(docker inspect --format '{{.State.ExitCode}}' "$name"); strategy: $run/output/$strategy"
