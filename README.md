# ork-pf2e-tools

Extracts the Pathfinder 2e and Starfinder 2e compendium data published by the [Foundry VTT PF2e system](https://github.com/foundryvtt/pf2e) and turns it into a compact, grep-friendly reference. It also installs a Claude Code skill (`pf2e-rules`) so Claude looks up rules there instead of answering from memory.

The data comes from the `json-assets.zip` file attached to each upstream release. There are separate releases for each game, tagged `pf2e-X.Y.Z` and `sf2e-X.Y.Z`. Together the two zips are about 40 MB. The extracted data is about 42 MB of plain text, one record per line, covering spells, feats, actions, conditions, traits, items, classes, ancestries, deities, creatures, hazards, rules journals, and more.

## Requirements

- Python 3.10 or later (standard library only)
- Network access to github.com
- Claude Code, to use the skill

## Extract the data and install the skill

```sh
./install.sh                                  # latest pf2e and sf2e releases
./install.sh --pf2e 8.5.0 --sf2e 1.5.0        # pin specific releases
./install.sh --pf2e pf2e-8.5.0                # full tag form also works; unpinned game uses latest
```

This does two things:

1. It runs `extract.py`, which finds the latest release tags if none were given. It downloads each `json-assets.zip` into memory (nothing is written to disk) and writes `skill/pf2e-rules/data/`.
2. It symlinks `skill/pf2e-rules` to `~/.claude/skills/pf2e-rules`.

Start a new Claude Code session afterwards so the skill loads.

To extract without installing the skill:

```sh
python3 extract.py --out skill/pf2e-rules/data [--pf2e TAG] [--sf2e TAG]
```

## Updating

Run `./install.sh --check` to compare the installed data with the latest releases. It prints the installed and latest tag for each game, and exits with status 1 if either is out of date (or no data is installed), so it works in scripts:

```sh
./install.sh --check || ./install.sh
```

Run `./install.sh` again to pick up the newest releases. Because the skill is a symlink, the new data takes effect right away. `data/VERSION` records the release tags and asset URLs the data came from.

## Querying the data by hand

```sh
S=skill/pf2e-rules/scripts/pf.py
$S "Fireball"                        # full record, one field per line
$S "Red Dragon (Young)" -g pf2e      # limit to one game
$S "Goblin Warrior" -f creature-lore # creature background (opt-in file)
$S -s 'flank' -f rules               # full-text regex search, lists matches
```

## Layout

```
extract.py                    # release json-assets.zip -> compact text
install.sh                    # extract + link skill into ~/.claude/skills
skill/pf2e-rules/
  SKILL.md                    # when Claude uses the skill; record format legend
  scripts/pf.py               # lookup / search tool
  data/                       # generated, not committed (see .gitignore)
    VERSION  sources.txt      # release tags; source-code abbreviations
    pf2e/*.txt  sf2e/*.txt    # one file per category, plus index.txt
```

The generated data is not committed. It's reproducible from the releases, and it's Paizo content published under the OGL/ORC licenses.
