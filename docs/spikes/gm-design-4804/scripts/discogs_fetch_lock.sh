# SPDX-License-Identifier: MIT
# Shared fetch discipline for every spike that reads data.discogs.com (sourced, not run).
#
# 1. One request at a time across all spikes: hold the global lock directory
#    $DUMPS/.fetch.lock (mkdir is atomic) for the whole life of every request, including
#    a full releases stream. The holder writes its pid, spike, and file into owner.txt.
# 2. A finished file in $DUMPS is never rewritten. A cached file has its own lock,
#    $DUMPS/<file>.lock, so a second spike waits for it instead of fetching it again.
# 3. Every curl writes its response headers to a file (-D), so the status and any
#    Retry-After are known without touching the body stream.
# 4. On HTTP 429, back off exponentially from 60 s (60, 120, 240, ...) for at most
#    MAX_429 retries (default 3), then stop with exit code 75. A Retry-After longer than
#    the next back-off also stops with 75: a ban is a data-access problem for a person
#    to resolve, not something to retry through.

DUMPS=${DUMPS:-$HOME/.cache/groovemap-spikes/dumps}
MAX_429=${MAX_429:-3}
SPIKE=${SPIKE:-gm-design-4804}

acquire_fetch_lock() {  # $1: what is being fetched
  mkdir -p "$DUMPS"
  until mkdir "$DUMPS/.fetch.lock" 2>/dev/null; do
    sleep 30
  done
  printf 'pid=%s spike=%s what=%s since=%s\n' "$$" "$SPIKE" "$1" "$(date -u +%FT%TZ)" \
    > "$DUMPS/.fetch.lock/owner.txt"
}

release_fetch_lock() {
  rm -f "$DUMPS/.fetch.lock/owner.txt"
  rmdir "$DUMPS/.fetch.lock" 2>/dev/null || true
}

# http_status HEADERS_FILE -> last status code in the (possibly redirected) header dump
http_status() {
  awk '/^HTTP\//{code=$2} END{print code+0}' "$1" 2>/dev/null
}

retry_after() {
  awk 'tolower($1)=="retry-after:"{gsub("\r","",$2); v=$2} END{print v+0}' "$1" 2>/dev/null
}

# backoff_or_stop ATTEMPT HEADERS_FILE: returns 0 after sleeping, or exits 75.
backoff_or_stop() {
  local attempt=$1 headers=$2 wait ra
  wait=$((60 * (1 << attempt)))
  ra=$(retry_after "$headers")
  if (( attempt >= MAX_429 )) || (( ra > wait )); then
    echo "HTTP 429 with retry-after ${ra}s on attempt $((attempt + 1)); stopping (exit 75)" >&2
    exit 75
  fi
  echo "HTTP 429; backing off ${wait}s" >&2
  sleep "$wait"
}
