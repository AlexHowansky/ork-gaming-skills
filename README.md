# ork-pf2e-tools

Extracts the Pathfinder 2e and Starfinder 2e compendium data published by the [Foundry VTT PF2e system](https://github.com/foundryvtt/pf2e) and turns it into a compact, grep-friendly reference. It also installs a Claude Code skill (`pf2e-rules`) so Claude looks up rules there instead of answering from memory.

The data comes from the `json-assets.zip` file attached to each upstream release. There are separate releases for each game, tagged `pf2e-X.Y.Z` and `sf2e-X.Y.Z`. Together the two zips are about 40 MB. The extracted data is about 42 MB of plain text, one record per line, covering spells, feats, actions, conditions, traits, items, classes, ancestries, deities, creatures, hazards, rules journals, and more.

## Requirements

- Python 3.6 or later (standard library only)
- Network access to github.com
- Claude Code, to use the skill

## Extract the data

```sh
./extract.py                               # latest pf2e and sf2e releases
./extract.py --pf2e 8.5.0 --sf2e 1.5.0     # pin specific releases
./extract.py --pf2e pf2e-8.5.0             # full tag form also works; unpinned game uses latest
```

`extract.py` finds the latest release tags if none were given. It downloads each `json-assets.zip` into memory (nothing is written to disk) and writes `skill/pf2e-rules/data/` next to the script, wherever you run it from. Pass `--out DIR` to write somewhere else.

## Install the skill

```sh
./install_skill.sh
```

This symlinks `skill/pf2e-rules` to `~/.claude/skills/pf2e-rules`. Extract the data first. Start a new Claude Code session afterwards so the skill loads.

## Updating

Run `./extract.py --check` to compare the installed data with the latest releases. It prints the installed and latest tag for each game, and exits with status 1 if either is out of date (or no data is installed), so it works in scripts:

```sh
./extract.py --check || ./extract.py
```

Run `./extract.py` again to pick up the newest releases. Because the skill is a symlink, the new data takes effect right away without reinstalling. `data/VERSION` records the release tags and asset URLs the data came from.

## Querying the data by hand

```sh
S=skill/pf2e-rules/scripts/pf.py
$S "Fireball"                        # full record, one field per line
$S "Red Dragon (Young)" -g pf2e      # limit to one game
$S "Goblin Warrior" -f creature-lore # creature background (opt-in file)
$S -s 'flank' -f rules               # full-text regex search, lists matches
```

## Discord bots

There are two interchangeable Discord bots that answer `/pf <query>`: a Python one in `bots/python/` (discord.py) and a Bun/TypeScript one in `bots/bun/` (discord.js). They look the same to users and give identical results. The Python bot reuses `pf.py` directly. The Bun bot is a port of it that reads the same data files and doesn't need Python. Run one or the other. Both register `/pf` and can use the same Discord application, but don't run both with the same token at once.

`/pf` searches Pathfinder 2e and Starfinder 2e together, and each result says which game it's from. Names autocomplete as you type. Results are private to the person who asked, with a **Share to channel** button to post them. When a query matches several records (including the same name in both games), a dropdown lets you switch between them. Long records page with ◀ ▶, and creatures with background text get a **Lore** button. If no name matches, the bot falls back to a full-text search and lists the hits.

Common setup:

1. Extract the data (`./extract.py`).
2. In the [Discord developer portal](https://discord.com/developers/applications), create an application, add a bot, and copy its token (from the **Bot** page, not the Public Key). No privileged intents are needed.
3. Invite it with `https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot+applications.commands&permissions=19456` (View Channels, Send Messages, Embed Links).
4. Register the slash command with `--sync` (below) once, and again whenever the command definition changes. Global commands can take a while to appear. Set `PF_GUILD_ID` in the env file to sync to a single server instantly while testing. If you synced an older version that also had `/sf`, this sync removes it.

Both bots load all data into memory at startup, so restart the service after `./extract.py` updates the data.

### Python

```sh
python3 -m venv bots/python/.venv
bots/python/.venv/bin/pip install -r bots/python/requirements.txt
cp bots/python/pfbot.env.example bots/python/pfbot.env && chmod 600 bots/python/pfbot.env   # set DISCORD_TOKEN

set -a; . bots/python/pfbot.env; set +a
bots/python/.venv/bin/python bots/python/pfbot.py --sync      # register /pf, then keep running
bots/python/.venv/bin/python bots/python/pfbot.py --verbose   # also log each interaction to the console

bots/python/.venv/bin/python bots/python/pfbot.py --preview "Red Dragon (Adult)"   # no Discord needed
bots/python/.venv/bin/python -m unittest discover bots/python
```

Service: edit the paths and user in `bots/python/pfbot.service`, copy it to `/etc/systemd/system/`, then `sudo systemctl enable --now pfbot`.

### Bun

Requires [Bun](https://bun.sh) 1.x.

```sh
cd bots/bun
bun install
cp .env.example .env && chmod 600 .env   # set DISCORD_TOKEN; Bun loads .env automatically

bun run sync     # register /pf, then keep running (later runs: bun run start)
bun run start --verbose   # also log each interaction and gateway event to the console

bun src/bot.ts --preview "Red Dragon (Adult)"   # no Discord needed
bun test
bun run typecheck
```

Service: edit the paths and user in `bots/bun/pfbot-bun.service`, copy it to `/etc/systemd/system/`, then `sudo systemctl enable --now pfbot-bun`.

## Layout

```
extract.py                    # release json-assets.zip -> compact text
install_skill.sh              # link skill into ~/.claude/skills
skill/pf2e-rules/
  SKILL.md                    # when Claude uses the skill; record format legend
  scripts/pf.py               # lookup / search tool
  data/                       # generated, not committed (see .gitignore)
    VERSION  sources.txt      # release tags; source-code abbreviations
    pf2e/*.txt  sf2e/*.txt    # one file per category, plus index.txt
bots/python/
  pfbot.py                    # Discord bot: /pf command, views
  store.py                    # in-memory data, lookup/search/autocomplete via pf.py
  render.py                   # record -> Discord markdown pages
  pfbot.service               # sample systemd unit
bots/bun/
  src/bot.ts                  # Discord bot (discord.js): /pf command, components
  src/store.ts                # port of pf.py + store.py
  src/render.ts               # port of render.py (same output)
  test/                       # bun test
  pfbot-bun.service           # sample systemd unit
```

This package does not include Pathfinder 2e game data. Users must obtain the source data separately and generate the local database using the included conversion tools. The generated data is not committed.
