#!/usr/bin/env bash
# Install a pre-push hook that runs scripts/lint.sh before pushing.
# Run once per clone: ./scripts/install-hooks.sh
set -euo pipefail
cd "$(dirname "$0")/.."

hook=".git/hooks/pre-push"
cat > "$hook" <<'EOF'
#!/usr/bin/env bash
# Bisque pre-push hook — runs the same checks as CI's lint jobs.
# Bypass for an emergency push with: git push --no-verify
exec "$(git rev-parse --show-toplevel)/scripts/lint.sh"
EOF
chmod +x "$hook"
echo "Installed $hook"
