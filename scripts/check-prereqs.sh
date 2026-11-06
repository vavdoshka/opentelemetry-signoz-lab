#!/usr/bin/env bash
# Checks everything `make up` needs, and says how to fix what is missing.
source "$(dirname "$0")/lib.sh"

failed=0
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  warn  %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; failed=1; }

need() {
  if command -v "$1" >/dev/null 2>&1; then ok "$1"; else bad "$1 is not installed. See Prerequisites in README.md"; fi
}

echo "Checking prerequisites for provider: $PROVIDER"
need docker
need kubectl
need helm
need python3
need "$PROVIDER"

if docker info >/dev/null 2>&1; then
  ok "Docker is running"
  memory_gb=$(( $(docker info --format '{{.MemTotal}}') / 1000000000 ))
  if [ "$memory_gb" -lt 8 ]; then
    bad "Docker has ${memory_gb} GB of memory. The lab needs at least 8 GB, and 10 GB is better"
  elif [ "$memory_gb" -lt 10 ]; then
    warn "Docker has ${memory_gb} GB of memory. 10 GB or more is recommended"
  else
    ok "Docker has ${memory_gb} GB of memory"
  fi
else
  bad "Docker is not running. Start it and try again"
fi

if python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  ok "Python is 3.9 or newer"
else
  bad "Python 3.9 or newer is required"
fi

if python3 -c 'import socket; socket.gethostbyname("app.localhost"); socket.gethostbyname("signoz.localhost")' 2>/dev/null; then
  ok "*.localhost names resolve"
else
  bad "app.localhost does not resolve. Run:
        echo '127.0.0.1 app.localhost signoz.localhost' | sudo tee -a /etc/hosts"
fi

cluster_exists=no
if [ "$PROVIDER" = k3d ] && k3d_cluster_exists; then cluster_exists=yes; fi
if [ "$PROVIDER" = kind ] && kind_cluster_exists; then cluster_exists=yes; fi
if [ "$cluster_exists" = no ]; then
  if python3 -c 'import socket; s=socket.socket(); s.settimeout(1); raise SystemExit(s.connect_ex(("127.0.0.1", 8080)) != 0)' 2>/dev/null; then
    bad "Port 8080 is already in use. Stop whatever is using it"
  else
    ok "Port 8080 is free"
  fi
fi

if [ "$failed" -ne 0 ]; then
  echo
  echo "Fix the items marked FAIL, then run this again."
  exit 1
fi
