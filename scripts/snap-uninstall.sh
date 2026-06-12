#!/usr/bin/env bash
# Local dev helper: full uninstall + cleanup of the ward snap and its build
# artifacts. Counterpart to snap-install.sh.
#
# Untracked by design (see .gitignore). Wipes:
#   - the installed snap (with --purge: no snapshot retained)
#   - any per-user $SNAP_USER_DATA under ~/snap/ward/ (consequence of --purge)
#   - locally-built ward_*.snap artifacts in the repo root
#   - snapcraft's build cache (parts/stage/prime via `snapcraft clean`)
#   - snapcraft's local state dir snap/.snapcraft/
#
# Does NOT touch this project's workshop (use `ward purge` for that).

set -euo pipefail

log() { echo "[snap-uninstall] $*"; }

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if snap list ward >/dev/null 2>&1; then
    log "Removing installed ward snap (requires sudo, --purge wipes user data)"
    sudo snap remove --purge ward
else
    log "ward snap not installed; skipping snap removal"
fi

if compgen -G "ward_*.snap" >/dev/null; then
    log "Deleting local .snap artifacts in $repo_root"
    rm -f ward_*.snap
else
    log "No local .snap artifacts to delete"
fi

if command -v snapcraft >/dev/null && [[ -f snap/snapcraft.yaml ]]; then
    log "Running 'snapcraft clean' to drop the LXD build cache"
    snapcraft clean --use-lxd 2>/dev/null || log "snapcraft clean failed (continuing)"
else
    log "Skipping snapcraft clean (snapcraft missing or snapcraft.yaml absent)"
fi

if [[ -d snap/.snapcraft ]]; then
    log "Removing snap/.snapcraft/ state directory"
    rm -rf snap/.snapcraft/
fi

log "Cleanup complete."
