#!/usr/bin/env bash
# Start a headless CARLA server. Idempotent: refuses to start twice on a port.
#
#   scripts/start_carla.sh [--port N] [--gpu N] [--mode docker|native] [--wait S]
#
# Blocks until the server actually ACCEPTS A CLIENT CONNECTION -- not until the
# container is up, and not for a fixed sleep. A container that is running but
# not yet listening is the single most common cause of a spurious "connection
# refused" at the start of a campaign.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PORT=2000
GPU=0
MODE=""
WAIT_S=180
IMAGE="carlasim/carla:0.9.16"
QUALITY="Low"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --gpu) GPU="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --wait) WAIT_S="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Read mode / image from config/local.yaml if not given on the command line.
if [[ -z "$MODE" ]]; then
  MODE="$(.venv/bin/python - <<'PY' 2>/dev/null || echo docker
import sys; sys.path.insert(0, "src")
from config import load_config
print((load_config("sim").get("carla") or {}).get("mode", "docker"))
PY
)"
fi

CONTAINER="carla_${PORT}"

# ---------------------------------------------------------------- docker cmd
# Works whether or not the invoking user is in the docker group.
# NOTE: `sg docker -c ...` PROMPTS FOR A PASSWORD ON STDIN when the invoking
# user is not listed in /etc/group for docker. Probing with it unguarded makes
# this script hang forever instead of failing. So: check /etc/group first, and
# still redirect stdin from /dev/null as a second line of defence.
in_docker_group() {
  getent group docker | awk -F: '{print $4}' | tr ',' '\n' | grep -qx "$(id -un)"
}

docker_cmd() {
  if timeout 10 docker info >/dev/null 2>&1 </dev/null; then
    docker "$@"
  elif in_docker_group; then
    sg docker -c "docker $(printf '%q ' "$@")" </dev/null
  else
    echo "ERROR: cannot reach the docker daemon and $(id -un) is not in the docker group." >&2
    echo "  Run:  sudo usermod -aG docker $(id -un)" >&2
    exit 3
  fi
}

# ------------------------------------------------------------ already up?
if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${PORT}\$"; then
  echo "REFUSING TO START: port ${PORT} is already listening."
  echo "  Existing server:"
  ss -ltnp 2>/dev/null | grep -E "[:.]${PORT}\b" || true
  echo "  Use a different --port, or stop it with: scripts/stop_carla.sh --port ${PORT}"
  exit 1
fi

if [[ "$MODE" == "docker" ]]; then
  if docker_cmd ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    STATE="$(docker_cmd inspect -f '{{.State.Status}}' "$CONTAINER")"
    if [[ "$STATE" == "running" ]]; then
      echo "REFUSING TO START: container ${CONTAINER} is already running."
      exit 1
    fi
    # -f, and tolerate failure: a container left in "created" state by a
    # docker run that itself failed (exit 125) is not removable by a plain
    # `docker rm` in every daemon version, and if it lingers it blocks every
    # later start on this port with a name conflict.
    echo "Removing ${STATE} container ${CONTAINER} ..."
    docker_cmd rm -f "$CONTAINER" >/dev/null 2>&1 || true
  fi

  echo "Starting CARLA (docker) image=${IMAGE} port=${PORT} gpu=${GPU} quality=${QUALITY}"
  docker_cmd run -d \
    --name "$CONTAINER" \
    --runtime=nvidia \
    --net=host \
    --env=NVIDIA_VISIBLE_DEVICES="${GPU}" \
    --env=NVIDIA_DRIVER_CAPABILITIES=all \
    "$IMAGE" \
    bash CarlaUE4.sh \
      -RenderOffScreen \
      -nosound \
      -quality-level="${QUALITY}" \
      -carla-rpc-port="${PORT}" \
    >/dev/null || {
      # Do not leave a half-created container behind: it blocks every later
      # start on this port with a name conflict, and the failure that caused
      # it is usually transient.
      echo "docker run failed; cleaning up any partial container" >&2
      docker_cmd rm -f "$CONTAINER" >/dev/null 2>&1 || true
      exit 6
    }
else
  CARLA_ROOT="$(.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "src")
from config import load_config
print((load_config("sim").get("carla") or {}).get("root", ""))
PY
)"
  if [[ -z "$CARLA_ROOT" || ! -x "${CARLA_ROOT}/CarlaUE4.sh" ]]; then
    echo "ERROR: native mode but CarlaUE4.sh not found under '${CARLA_ROOT}'." >&2
    echo "  Set carla.root in config/local.yaml" >&2
    exit 4
  fi
  mkdir -p data/logs
  echo "Starting CARLA (native) root=${CARLA_ROOT} port=${PORT} gpu=${GPU}"
  CUDA_VISIBLE_DEVICES="${GPU}" nohup "${CARLA_ROOT}/CarlaUE4.sh" \
    -RenderOffScreen -nosound -quality-level="${QUALITY}" \
    -carla-rpc-port="${PORT}" \
    > "data/logs/carla_${PORT}.log" 2>&1 &
  echo "  pid $! -> data/logs/carla_${PORT}.log"
fi

# --------------------------------------------- wait for an ACTUAL connection
echo -n "Waiting for CARLA to accept a client connection on port ${PORT} "
START=$(date +%s)
while true; do
  if .venv/bin/python - "$PORT" >/dev/null 2>&1 <<'PY'
import sys, carla
c = carla.Client("127.0.0.1", int(sys.argv[1]))
c.set_timeout(2.0)
c.get_server_version()
PY
  then
    ELAPSED=$(( $(date +%s) - START ))
    echo " ready after ${ELAPSED}s"
    .venv/bin/python - "$PORT" <<'PY'
import sys, carla
c = carla.Client("127.0.0.1", int(sys.argv[1])); c.set_timeout(10.0)
print(f"  server={c.get_server_version()}  client={c.get_client_version()}")
print(f"  map={c.get_world().get_map().name}")
PY
    exit 0
  fi
  ELAPSED=$(( $(date +%s) - START ))
  if (( ELAPSED > WAIT_S )); then
    echo
    echo "TIMED OUT after ${WAIT_S}s -- CARLA did not accept a connection." >&2
    if [[ "$MODE" == "docker" ]]; then
      echo "--- last 40 lines of container log ---" >&2
      docker_cmd logs --tail 40 "$CONTAINER" >&2 || true
    else
      tail -40 "data/logs/carla_${PORT}.log" >&2 || true
    fi
    exit 5
  fi
  echo -n "."
  sleep 3
done
