#!/usr/bin/env bash
# Link skills into ~/.claude/skills. Generate their data first: ./extract_pf2e.py for
# pf2e, ./extract_hero.py for hero, ./extract_cypher.py for cypher, ./extract_dnd5e.py for dnd5e.
# one-shot needs no data.
# Usage: ./install_skills.sh [SKILL...]   (default: pf2e hero cypher dnd5e one-shot)
set -euo pipefail
cd "$(dirname "$0")"
skills=("$@")
[[ ${#skills[@]} -gt 0 ]] || skills=(pf2e hero cypher dnd5e one-shot)
mkdir -p ~/.claude/skills
for s in "${skills[@]}"; do
    if [[ ! -f skills/$s/SKILL.md ]]; then
        echo "error: no skill named $s in skills/" >&2
        exit 1
    fi
    case $s in
        pf2e | hero | cypher | dnd5e) extractor=extract_$s.py ;;
        *) extractor= ;;
    esac
    if [[ -n $extractor && ! -f skills/$s/data/VERSION ]]; then
        echo "warning: no data in skills/$s/data yet; run ./$extractor" >&2
    fi
    ln -sfn "$PWD/skills/$s" ~/.claude/skills/$s
    echo "linked ~/.claude/skills/$s -> $PWD/skills/$s"
done
