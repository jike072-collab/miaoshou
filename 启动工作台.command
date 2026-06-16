#!/bin/zsh
set -e
cd "$(dirname "$0")"

if curl -fsS "http://127.0.0.1:8765/api/health" >/dev/null 2>&1; then
  open "http://127.0.0.1:8765"
  exit 0
fi

python3 app.py &
SERVER_PID=$!
trap 'kill "$SERVER_PID" >/dev/null 2>&1 || true' INT TERM EXIT

for attempt in {1..50}; do
  if curl -fsS "http://127.0.0.1:8765/api/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    wait "$SERVER_PID"
    exit 1
  fi
  sleep 0.1
done

if ! curl -fsS "http://127.0.0.1:8765/api/health" >/dev/null 2>&1; then
  echo "工作台未能在5秒内启动"
  exit 1
fi

open "http://127.0.0.1:8765"
wait $SERVER_PID
trap - EXIT
