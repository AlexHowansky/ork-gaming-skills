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

## Discord bot

`bot/` is a Discord bot that answers `/pf <query>` (Pathfinder 2e) and `/sf <query>` (Starfinder 2e) using the same data and matching as `pf.py`. Names autocomplete as you type. Results are private to the person who asked, with a **Share to channel** button to post them. When a query matches several records, a dropdown lets you switch between them. Long records page with ◀ ▶, and creatures with background text get a **Lore** button. If no name matches, the bot falls back to a full-text search and lists the hits.

Setup:

1. Extract the data (`./install.sh`, or `python3 extract.py --out skill/pf2e-rules/data`).
2. In the [Discord developer portal](https://discord.com/developers/applications), create an application, add a bot, and copy its token. No privileged intents are needed.
3. Invite it with `https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot+applications.commands&permissions=19456` (View Channels, Send Messages, Embed Links).
4. Install and configure:
   ```sh
   python3 -m venv bot/.venv
   bot/.venv/bin/pip install -r bot/requirements.txt
   cp bot/pfbot.env.example bot/pfbot.env && chmod 600 bot/pfbot.env   # set DISCORD_TOKEN
   ```
5. Register the slash commands once, and again whenever the command definitions change:
   ```sh
   set -a; . bot/pfbot.env; set +a
   bot/.venv/bin/python bot/pfbot.py --sync
   ```
   Global commands can take a while to appear. Set `PF_GUILD_ID` to sync to a single server instantly while testing.
6. Run it as a service: edit the paths and user in `bot/pfbot.service`, copy it to `/etc/systemd/system/`, then `sudo systemctl enable --now pfbot`.

The bot loads all data into memory at startup, so restart it (`sudo systemctl restart pfbot`) after `./install.sh` updates the data.

To check formatting without connecting to Discord:

```sh
bot/.venv/bin/python bot/pfbot.py --preview pf2e "Red Dragon (Adult)"
bot/.venv/bin/python -m unittest discover bot
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
bot/
  pfbot.py                    # Discord bot: /pf and /sf commands, views
  store.py                    # in-memory data, lookup/search/autocomplete via pf.py
  render.py                   # record -> Discord markdown pages
  pfbot.service               # sample systemd unit
```

The generated data is not committed. It's reproducible from the releases, and it's Paizo content published under the OGL/ORC licenses.
