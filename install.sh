#!/usr/bin/env bash
# Extract the data from the foundryvtt/pf2e release zips and link the skill into ~/.claude/skills.
# Usage: ./install.sh [--pf2e TAG] [--sf2e TAG]   (default: latest releases)
set -euo pipefail
cd "$(dirname "$0")"
python3 extract.py --out skill/pf2e-rules/data "$@"
mkdir -p ~/.claude/skills
ln -sfn "$PWD/skill/pf2e-rules" ~/.claude/skills/pf2e-rules
echo "linked ~/.claude/skills/pf2e-rules -> $PWD/skill/pf2e-rules"
