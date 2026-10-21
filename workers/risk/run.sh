#!/usr/bin/env sh
# Risk worker: claims and executes queued 'risk' jobs from the shared database queue (ADR-0003).
# Domain code lives in apps/api/taxcris (modular monolith); this is a separately scalable process.
set -eu
exec taxcris-worker --queue risk "$@"
