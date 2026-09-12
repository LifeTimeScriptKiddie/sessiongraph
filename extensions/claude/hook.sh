#!/usr/bin/env bash
# Opt-in Claude Code hook runner (do not install globally without approval).
# Usage in settings: command → absolute path to this script.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec node --experimental-strip-types "$ROOT/extensions/claude/hook.ts"
