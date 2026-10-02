#!/usr/bin/env bash
# Link skills into ~/.claude/skills. Generate their data first: ./extract_pf2e.py for
# pf2e, ./extract_hero.py for hero, ./extract_cypher.py for cypher, ./extract_dnd5e.py for dnd5e.
# Usage: ./install_skills.sh [SKILL...]   (default: pf2e hero cypher dnd5e)
set -euo pipefail
cd "$(dirname "$0")"
skills=("$@")
[[ ${#skills[@]} -gt 0 ]] || skills=(pf2e hero cypher dnd5e)
mkdir -p ~/.claude/skills
for s in "${skills[@]}"; do
    if [[ ! -f skill/$s/SKILL.md ]]; then
        echo "error: no skill named $s in skill/" >&2
        exit 1
    fi
    if [[ ! -f skill/$s/data/VERSION ]]; then
        extractor=extract_pf2e.py
        [[ $s == hero ]] && extractor=extract_hero.py
        [[ $s == cypher ]] && extractor=extract_cypher.py
        [[ $s == dnd5e ]] && extractor=extract_dnd5e.py
        echo "warning: no data in skill/$s/data yet; run ./$extractor" >&2
    fi
    ln -sfn "$PWD/skill/$s" ~/.claude/skills/$s
    echo "linked ~/.claude/skills/$s -> $PWD/skill/$s"
done
