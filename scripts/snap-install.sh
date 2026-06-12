#!/usr/bin/env bash
# Local dev helper: full rebuild + reinstall of the ward snap.
#
# Untracked by design (see .gitignore). Intended for tight iteration loops
# where you've just edited Python sources and want to re-exercise the snap
# code path (which differs subtly from `uv run` — different interpreter
# bundling, classic-confinement env, etc.).
#
# Pinned to the LXD backend because Workshop already pulls LXD in; this
# avoids snapcraft's auto-detect spinning up a Multipass VM on machines
# that don't have one.

set -euo pipefail

die() { echo "[snap-install] ERROR: $*" >&2; exit 1; }
log() { echo "[snap-install] $*"; }

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

command -v snapcraft >/dev/null \
    || die "snapcraft not installed. Install with: sudo snap install snapcraft --classic"

log "Removing any stale local .snap artifacts in $repo_root"
rm -f ward_*.snap

log "Cleaning previous snapcraft build state (full rebuild)"
snapcraft clean --use-lxd

log "Packing snap (this may take a minute or two)"
snapcraft pack --use-lxd

snap_file="$(ls -1t ward_*.snap 2>/dev/null | head -n1 || true)"
[[ -n "${snap_file:-}" ]] || die "snapcraft pack produced no ward_*.snap artifact"
log "Built: $snap_file"

log "Installing $snap_file (requires sudo)"
sudo snap install --classic --dangerous "./$snap_file"

log "Installed:"
snap list ward | sed 's/^/    /'
log "Resolved 'ward' to: $(command -v ward || echo '<not on PATH>')"
log "Done."
