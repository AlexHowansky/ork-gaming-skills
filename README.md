# ork-gaming-skills

Provides tools to extract and convert role playing game system rules to a small portable format that can be efficently referenced by AI skills.

*No third-party content is included or redistributed here. This repository contains software only to manipulate data.*

## Requirements

- Python 3.6 or later (standard library only)
- Network access to github.com
- Claude Code, to use the skill

## Includes

- [Pathfinder 2e](#pathfinderstarfinder)
- [Starfinder 2e](#pathfinderstarfinder)
- [HERO System 5th ed](#hero-system)
- [HERO System 6th ed](#hero-system)

### Pathfinder/Starfinder

Extracts the Pathfinder 2e and Starfinder 2e compendium data published by the [Foundry VTT PF2e system](https://github.com/foundryvtt/pf2e) and turns it into a compact, grep-friendly reference. It also installs a Claude Code skill (`pf2e`) so Claude looks up rules there instead of answering from memory.

The data comes from the `json-assets.zip` file attached to each upstream release. There are separate releases for each game, tagged `pf2e-X.Y.Z` and `sf2e-X.Y.Z`. Together the two zips are about 40 MB. The extracted data is about 42 MB of plain text, one record per line, covering spells, feats, actions, conditions, traits, items, classes, ancestries, deities, creatures, hazards, rules journals, and more.

```sh
./extract_pf2e.py                               # extract rules from the latest pf2e and sf2e releases
./extract_pf2e.py --pf2e 8.5.0 --sf2e 1.5.0     # pin specific releases
```

`extract_pf2e.py` finds the latest release tags if none were given. It downloads each `json-assets.zip` into memory (nothing is written to disk) and writes `skill/pf2e/data/` next to the script, wherever you run it from. Pass `--out DIR` to write somewhere else.

#### Updating

Run `./extract_pf2e.py --check` to compare the installed data with the latest releases. It prints the installed and latest tag for each game, and exits with status 1 if either is out of date (or no data is installed), so it works in scripts:

```sh
./extract_pf2e.py --check || ./extract_pf2e.py
```

Run `./extract_pf2e.py` again to pick up the newest releases. Because the skill is a symlink, the new data takes effect right away without reinstalling. `data/VERSION` records the release tags and asset URLs the data came from.


### HERO System

Data is extracted directly from the HERO Designer software `HD6.JAR` file, which you must already own.

The `hero` skill provides information for Powers, Advantages, Limitations, Skills, Perks, Talents, Characteristics, Martial Arts maneuvers, Disadvantages/Complications, languages, and the Vehicle/Base/Automaton/AI/Computer templates, with their costs and HERO Designer's help text.

The rules must first be extracted to JSON via the `ork-hero-extract-rules` tool from [AlexHowansky/ork-hero-export-renderer](https://github.com/AlexHowansky/ork-hero-export-renderer) and then converted to the compact format:

```sh
npx ork-hero-extract-rules /path/to/HD6.jar   # from ork-hero-export-renderer; writes ./rules
./extract_hero.py --rules ./rules             # writes skill/hero/data/
```

Without `--rules`, `extract_hero.py` uses `$ORK_HERO_RULES`, then `../ork-hero-export-renderer/rules`, then `./rules`. Re-run both steps after installing a new HERO Designer build.

## Install the skills

```sh
./install_skills.sh
```

This symlinks `skill/pf2e` and `skill/hero` into `~/.claude/skills/`. Pass skill names (`./install_skills.sh pf2e`) to link only some. Extract the data first. Start a new Claude Code session afterwards so the skills load.

## Querying the data by hand

```sh
S=skill/pf2e/scripts/pf.py
$S "Fireball"                        # full record, one field per line
$S "Red Dragon (Young)" -g pf2e      # limit to one game
$S "Goblin Warrior" -f creature-lore # creature background (opt-in file)
$S -s 'flank' -f rules               # full-text regex search, lists matches
```

```sh
H=skill/hero/scripts/hero.py
$H "Blast"                           # full record, 6e first
$H ENERGYBLAST -g 5e                 # by HERO Designer id, which is the same in both editions
$H "Flight" -t Vehicle6E             # one template's version
$H -s 'hit location' -f modifiers    # full-text regex search
```


## Discord bots

There are two interchangeable Discord bots that answer `/pf <query>` and `/hero <query>`: a Python one in `bots/python/` (discord.py) and a Bun/TypeScript one in `bots/bun/` (discord.js). They look the same to users and give identical results. The Python bot reuses `pf.py` and `hero.py` directly. The Bun bot is a port of it that reads the same data files and doesn't need Python. Run one or the other. Both register the same commands and can use the same Discord application, but don't run both with the same token at once.

`/pf` searches Pathfinder 2e and Starfinder 2e together, and each result says which game it's from. `/hero` searches HERO System 6e and 5e together, 6e first, and also matches HERO Designer ids (e.g. `ENERGYBLAST`). Its results name the edition, the template (`Main6E`, `Vehicle6E`, ...) and the id. `/hero` is only registered if the HERO data has been extracted. Since that data is Hero Games' copyrighted material, only offer `/hero` on servers where that's appropriate. Names autocomplete as you type. Results are private to the person who asked, with a **Share to channel** button to post them. When a query matches several records (including the same name in both games), a dropdown lets you switch between them. Long records page with ◀ ▶, and creatures with background text get a **Lore** button. If no name matches, the bot falls back to a full-text search and lists the hits. In `/hero`, the dropdown also lists the same ability's versions in other templates.

Common setup:

1. Extract the data.
2. In the [Discord developer portal](https://discord.com/developers/applications), create an application, add a bot, and copy its token (from the **Bot** page, not the Public Key). No privileged intents are needed.
3. Invite it with `https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot+applications.commands&permissions=19456` (View Channels, Send Messages, Embed Links).
4. Register the slash commands with `--sync` (below) once, and again whenever the command definitions change or you add or remove the HERO data. Global commands can take a while to appear. Set `PF_GUILD_ID` in the env file to sync to a single server instantly while testing. If you synced an older version that also had `/sf`, this sync removes it.

Both bots load all data into memory at startup, so restart the service after `./extract_pf2e.py` or `./extract_hero.py` updates the data.

### Python

```sh
python3 -m venv bots/python/.venv
bots/python/.venv/bin/pip install -r bots/python/requirements.txt
cp bots/python/pfbot.env.example bots/python/pfbot.env && chmod 600 bots/python/pfbot.env   # set DISCORD_TOKEN

set -a; . bots/python/pfbot.env; set +a
bots/python/.venv/bin/python bots/python/pfbot.py --sync      # register /pf and /hero, then keep running
bots/python/.venv/bin/python bots/python/pfbot.py --verbose   # also log each interaction to the console

bots/python/.venv/bin/python bots/python/pfbot.py --preview "Red Dragon (Adult)"   # no Discord needed
bots/python/.venv/bin/python bots/python/pfbot.py --preview "Flight" --hero         # same, for /hero
bots/python/.venv/bin/python -m unittest discover bots/python
```

Service: edit the paths and user in `bots/python/pfbot.service`, copy it to `/etc/systemd/system/`, then `sudo systemctl enable --now pfbot`.

### Bun

Requires [Bun](https://bun.sh) 1.x.

```sh
cd bots/bun
bun install
cp .env.example .env && chmod 600 .env   # set DISCORD_TOKEN; Bun loads .env automatically

bun run sync     # register /pf and /hero, then keep running (later runs: bun run start)
bun run start --verbose   # also log each interaction and gateway event to the console

bun src/bot.ts --preview "Red Dragon (Adult)"   # no Discord needed
bun src/bot.ts --preview "Flight" --hero        # same, for /hero
bun test
bun run typecheck
```

Service: edit the paths and user in `bots/bun/pfbot-bun.service`, copy it to `/etc/systemd/system/`, then `sudo systemctl enable --now pfbot-bun`.

## Layout

```
extract_pf2e.py               # release json-assets.zip -> compact text
extract_hero.py               # HERO Designer rules JSON -> compact text
install_skills.sh             # link skills into ~/.claude/skills
skill/pf2e/
  SKILL.md                    # when Claude uses the skill; record format legend
  scripts/pf.py               # lookup / search tool
  data/                       # generated, not committed (see .gitignore)
    VERSION  sources.txt      # release tags; source-code abbreviations
    pf2e/*.txt  sf2e/*.txt    # one file per category, plus index.txt
skill/hero/
  SKILL.md                    # when Claude uses the skill; record format legend
  scripts/hero.py             # lookup / search tool
  data/                       # generated, not committed (Hero Games' copyright)
    VERSION                   # HERO Designer build the data came from
    5e/*.txt  6e/*.txt        # one file per category, plus index.txt
bots/python/
  pfbot.py                    # Discord bot: /pf and /hero commands, views
  store.py                    # in-memory data, lookup/search/autocomplete via pf.py and hero.py
  render.py                   # record -> Discord markdown pages
  pfbot.service               # sample systemd unit
bots/bun/
  src/bot.ts                  # Discord bot (discord.js): /pf and /hero commands, components
  src/store.ts                # port of pf.py + hero.py + store.py
  src/render.ts               # port of render.py (same output)
  test/                       # bun test
  pfbot-bun.service           # sample systemd unit
```
