#!/bin/bash
# Runs agent.py under a watchdog: if its log file stops growing for
# IDLE_LIMIT seconds (browser hung/frozen), the process is killed and
# restarted automatically. agent.py itself resumes from output/listings.json
# on every restart, so no progress is lost. Stops once agent.py exits
# cleanly (exit code 0), meaning it finished and wrote the final report.
cd "$(dirname "$0")"
source venv/bin/activate

LOG="${1:-output/run.log}"
IDLE_LIMIT=240

while true; do
  caffeinate -d -i -s -m python -u agent.py >> "$LOG" 2>&1 &
  AGENT_PID=$!
  LAST_SIZE=-1
  LAST_CHANGE=$(date +%s)

  while kill -0 "$AGENT_PID" 2>/dev/null; do
    sleep 20
    CUR_SIZE=$(wc -c < "$LOG" 2>/dev/null || echo 0)
    if [ "$CUR_SIZE" != "$LAST_SIZE" ]; then
      LAST_SIZE=$CUR_SIZE
      LAST_CHANGE=$(date +%s)
    else
      NOW=$(date +%s)
      if [ $((NOW - LAST_CHANGE)) -gt $IDLE_LIMIT ]; then
        echo "[$(date)] No progress for ${IDLE_LIMIT}s — killing stuck browser session and restarting" >> "$LOG"
        pkill -9 -P "$AGENT_PID" 2>/dev/null
        kill -9 "$AGENT_PID" 2>/dev/null
        break
      fi
    fi
  done

  wait "$AGENT_PID" 2>/dev/null
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date)] agent.py finished successfully. Supervisor stopping." >> "$LOG"
    break
  fi

  echo "[$(date)] Restarting agent.py (previous exit code: $EXIT_CODE)..." >> "$LOG"
  sleep 5
done
