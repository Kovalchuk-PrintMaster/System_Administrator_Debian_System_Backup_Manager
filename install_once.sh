#!/usr/bin/env bash
# First install and optional initial GitHub publication. Never formats any disk.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET="/opt/forprint-utils/system-backup-manager"
REPO="https://github.com/Kovalchuk-PrintMaster/System_Administrator_Debian_System_Backup_Manager.git"
[[ "$EUID" -eq 0 ]] || { echo '[SBM] ERROR: execute as root'; exit 1; }
[[ "${1:-}" == '--publish' || "${1:-}" == '--install-only' ]] || { echo 'Usage: bash install_once.sh --publish|--install-only'; exit 2; }
[[ ! -e "$TARGET" ]] || { echo "[SBM] ERROR: $TARGET already exists; will not overwrite"; exit 1; }
[[ -f "$ROOT/scripts/sbm.py" && -f "$ROOT/Makefile" ]] || { echo '[SBM] ERROR: incomplete source package'; exit 1; }
mkdir -p /opt/forprint-utils
cp -a -- "$ROOT" "$TARGET"
cd "$TARGET"
make check
printf '[SBM] INSTALL=PASS TARGET=%s\n' "$TARGET"
if [[ "$1" == '--publish' ]]; then
  command -v git >/dev/null || { echo '[SBM] ERROR: Git not installed; project installed but not published'; exit 1; }
  git init -b main
  git remote add origin "$REPO"
  git add README_UA.md Makefile .gitignore install_once.sh config docs scripts/sbm.py tests .github/workflows
  git diff --cached --check
  git commit -m 'Bootstrap guarded System Backup Manager CLI and Makefile'
  git push -u origin main
  echo '[SBM] GITHUB=PASS_PUSHED'
fi
printf '[SBM] Next: cd %s && make inspect\n' "$TARGET"
