#!/usr/bin/env bash
# Link the pf2e-rules skill into ~/.claude/skills. Run ./extract.py first to generate its data.
# Usage: ./install_skill.sh
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f skill/pf2e-rules/data/VERSION ]]; then
    echo "warning: no data in skill/pf2e-rules/data yet; run ./extract.py" >&2
fi
mkdir -p ~/.claude/skills
ln -sfn "$PWD/skill/pf2e-rules" ~/.claude/skills/pf2e-rules
echo "linked ~/.claude/skills/pf2e-rules -> $PWD/skill/pf2e-rules"
