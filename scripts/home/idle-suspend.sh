#!/usr/bin/env bash
# Suspend the home PC after IDLE_CHECKS consecutive idle checks (timer: every 5 min). Idle means: no
# `experiment` sleep inhibitor (scripts/home-run.sh), no SSH connection, nobody logged in at the desktop.
# Install: /usr/local/bin/idle-suspend.sh plus idle-suspend.{service,timer} in /etc/systemd/system.
set -euo pipefail
state=/run/idle-suspend.count
busy() {
  systemd-inhibit --list | grep -q experiment && return 0
  [ -n "$(ss -Htn state established '( sport = :22 )')" ] && return 0
  # a desktop session on seat0 (not the login screen): the desktop's own power settings decide
  loginctl list-sessions --no-legend | awk '$4 == "seat0" && $3 != "sddm"' | grep -q .
}
if busy; then echo 0 >"$state"; exit 0; fi
n=$(($(cat "$state" 2>/dev/null || echo 0) + 1))
if ((n >= ${IDLE_CHECKS:-6})); then
  echo 0 >"$state"  # reset first, so the PC gets a full grace period after the next wake-up
  systemctl suspend --check-inhibitors=yes  # a timer call ignores inhibitors unless told otherwise
else
  echo "$n" >"$state"
fi
