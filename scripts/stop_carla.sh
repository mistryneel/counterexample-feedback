#!/usr/bin/env bash
# Stop CARLA cleanly, including orphans. Idempotent: safe when nothing is up.
#
#   scripts/stop_carla.sh [--port N | --all]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PORT=""
ALL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --all) ALL=1; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -z "$PORT" && $ALL -eq 0 ]] && PORT=2000

# See start_carla.sh: an unguarded `sg docker` probe prompts on stdin and hangs.
in_docker_group() {
  getent group docker | awk -F: '{print $4}' | tr ',' '\n' | grep -qx "$(id -un)"
}

docker_cmd() {
  if timeout 10 docker info >/dev/null 2>&1 </dev/null; then docker "$@"
  elif in_docker_group; then sg docker -c "docker $(printf '%q ' "$@")" </dev/null
  else return 1; fi
}

stopped_any=0

# ------------------------------------------------------------ containers
if docker_cmd ps -a --format '{{.Names}}' >/dev/null 2>&1; then
  if [[ $ALL -eq 1 ]]; then
    NAMES="$(docker_cmd ps -a --format '{{.Names}}' | grep -E '^carla_[0-9]+$' || true)"
  else
    NAMES="$(docker_cmd ps -a --format '{{.Names}}' | grep -x "carla_${PORT}" || true)"
  fi
  for n in $NAMES; do
    echo "Stopping container ${n} ..."
    docker_cmd stop -t 20 "$n" >/dev/null 2>&1 || true
    docker_cmd rm "$n" >/dev/null 2>&1 || true
    stopped_any=1
  done
else
  echo "note: docker daemon unreachable; skipping container cleanup" >&2
fi

# --------------------------------------------------- native / orphan procs
# CarlaUE4 leaves a CarlaUE4-Linux-Shipping child behind if the wrapper is
# killed on its own. Both are matched here -- that orphan is what holds the
# RPC port and makes the next start_carla.sh fail with "already listening".
PATTERNS=("CarlaUE4-Linux-Shipping" "CarlaUE4\.sh")
TARGET_PIDS=()
for pat in "${PATTERNS[@]}"; do
  PIDS="$(pgrep -f "$pat" || true)"
  for pid in $PIDS; do
    if [[ $ALL -eq 0 && -n "$PORT" ]]; then
      # Only kill a process actually carrying this rpc port.
      if ! tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q -- "-carla-rpc-port=${PORT}"; then
        continue
      fi
    fi
    echo "Terminating pid ${pid} (${pat}) ..."
    kill -TERM "$pid" 2>/dev/null || true
    TARGET_PIDS+=("$pid")
    stopped_any=1
  done
done

# Escalate ONLY to the pids we actually signalled.
#
# This block previously re-ran `pgrep -f CarlaUE4-Linux-Shipping` and
# SIGKILLed everything it found, ignoring the port filter entirely. With
# several instances running for a parallel campaign, `stop_carla.sh --port
# 2050` killed all of them (observed: three containers exited 137). Never
# widen the target set during escalation.
if [[ ${#TARGET_PIDS[@]} -gt 0 ]]; then
  for _ in $(seq 1 20); do
    sleep 0.5
    still=0
    for pid in "${TARGET_PIDS[@]}"; do
      kill -0 "$pid" 2>/dev/null && still=1
    done
    [[ $still -eq 0 ]] && break
  done
  for pid in "${TARGET_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      echo "  pid ${pid} did not exit on SIGTERM; sending SIGKILL"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
fi

if [[ $stopped_any -eq 0 ]]; then
  echo "Nothing to stop."
else
  echo "Done."
fi

# ------------------------------------------------------------- final check
if [[ -n "$PORT" ]]; then
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${PORT}\$"; then
    echo "WARNING: port ${PORT} is STILL listening after cleanup:" >&2
    ss -ltnp 2>/dev/null | grep -E "[:.]${PORT}\b" >&2 || true
    exit 1
  fi
  echo "Port ${PORT} is free."
fi
