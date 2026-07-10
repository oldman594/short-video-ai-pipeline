#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
HOOK_PATH="$ROOT_DIR/.git/hooks/pre-commit"

mkdir -p "$(dirname "$HOOK_PATH")"

cat > "$HOOK_PATH" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

python3 scripts/check_file_line_limits.py --staged
HOOK

chmod +x "$HOOK_PATH"
echo "Installed pre-commit hook: $HOOK_PATH"
