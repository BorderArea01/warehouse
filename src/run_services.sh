set -e

PID_FILE=/app/main.pid
FLAG_FILE=/app/restart_main.flag

while true; do
  python -u -m src.main &
  pid=$!
  echo "$pid" > "$PID_FILE"
  wait "$pid"
  if [ -f "$FLAG_FILE" ]; then
    rm -f "$FLAG_FILE"
    continue
  fi
  exit $?
done
