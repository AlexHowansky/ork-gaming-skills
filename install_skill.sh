#!/usr/bin/env bash
# Link skills into ~/.claude/skills. Generate their data first: ./extract.py for
# pf2e-rules, ./extract_hero.py for hero.
# Usage: ./install_skill.sh [SKILL...]   (default: pf2e-rules hero)
set -euo pipefail
cd "$(dirname "$0")"
skills=("$@")
[[ ${#skills[@]} -gt 0 ]] || skills=(pf2e-rules hero)
mkdir -p ~/.claude/skills
for s in "${skills[@]}"; do
    if [[ ! -f skill/$s/SKILL.md ]]; then
        echo "error: no skill named $s in skill/" >&2
        exit 1
    fi
    if [[ ! -f skill/$s/data/VERSION ]]; then
        extractor=extract.py
        [[ $s == hero ]] && extractor=extract_hero.py
        echo "warning: no data in skill/$s/data yet; run ./$extractor" >&2
    fi
    ln -sfn "$PWD/skill/$s" ~/.claude/skills/$s
    echo "linked ~/.claude/skills/$s -> $PWD/skill/$s"
done
