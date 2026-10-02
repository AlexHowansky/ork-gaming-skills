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
- [Cypher System](#cypher-system)
- [Dungeons & Dragons 5e (2014 and 2024)](#dungeons--dragons-5e)

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

### Cypher System

Extracts the Cypher System Reference Document from the [Cypher SRD Compendium](https://github.com/mrkwnzl/cyphersystem-compendium) Foundry VTT module and turns it into the same compact format. It also installs a Claude Code skill (`cypher`) so Claude looks up rules there instead of answering from memory.

The data comes from the `release.zip` file attached to each upstream release (about 44 MB, mostly token images). The module stores its compendiums as LevelDB databases. `extract_cypher.py` reads them with its own small reader, so it still needs only the standard library. The extracted data is about 3 MB of plain text: abilities, skills and inabilities, cyphers, artifacts, equipment, weapons, armor, creatures and NPCs, vehicles and starships, power shifts, roll tables, and the full SRD text (including the genre rulebooks), one record per line. The SRD's types, flavors, descriptors and foci can be looked up by name.

```sh
./extract_cypher.py                  # extract from the latest release
./extract_cypher.py --tag 3.12.1     # pin a specific release
./extract_cypher.py --check || ./extract_cypher.py   # update only when a newer release exists
```

It downloads `release.zip` into memory (nothing is written to disk) and writes `skill/cypher/data/` next to the script. Pass `--out DIR` to write somewhere else. `data/VERSION` records the release tag and asset URL. The content is Cypher System material owned by Monte Cook Games, used under the Cypher System Open License.

### Dungeons & Dragons 5e

Extracts the D&D 5e System Reference Documents from the [Foundry VTT dnd5e system](https://github.com/foundryvtt/dnd5e) and turns them into the same compact format. Both rule sets are included: the 2024 rules (SRD 5.2) and the 2014 rules (SRD 5.1). It also installs a Claude Code skill (`dnd5e`) so Claude looks up rules there instead of answering from memory.

The data comes from the `dnd5e-release-X.Y.Z.zip` file attached to each upstream release. The zip is about 110 MB, but almost all of that is token art. `extract_dnd5e.py` reads the zip's directory and fetches only the compendium packs (about 11 MB) with HTTP range requests. The packs are LevelDB databases, read with the same small reader as the Cypher extractor. The extracted data is about 4 MB of plain text, split into `2024/` and `2014/`: spells and spell lists, classes, subclasses and class features, species, backgrounds, feats, equipment and magic items, monsters, monster features, vehicles, the rules and glossary, and roll tables, one record per line.

The system writes much of its text with Foundry roll enrichers (`[[/attack]]`, `[[/damage average]]`, `[[lookup @save.dc.value]]`, ...) that are only filled in when Foundry renders a page. The extractor fills them in the same way, deriving each monster's ability modifiers, proficiency bonus, AC, attack bonuses, damage averages and save DCs from its stat block. Foundry implementation notes are dropped. So are the pages the system marks as "Free Rules" content, which isn't covered by the SRD's license.

```sh
./extract_dnd5e.py                   # extract from the latest release
./extract_dnd5e.py --tag 6.0.5       # pin a specific release (release-6.0.5)
./extract_dnd5e.py --check || ./extract_dnd5e.py   # update only when a newer release exists
```

Nothing is written to disk except the output in `skill/dnd5e/data/` next to the script. Pass `--out DIR` to write somewhere else. `data/VERSION` records the release tag and asset URL. The SRD 5.1 and SRD 5.2 are © Wizards of the Coast LLC, licensed under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

## Install the skills

```sh
./install_skills.sh
```

This symlinks `skill/pf2e`, `skill/hero`, `skill/cypher` and `skill/dnd5e` into `~/.claude/skills/`. Pass skill names (`./install_skills.sh pf2e`) to link only some. Extract the data first. Start a new Claude Code session afterwards so the skills load.

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

```sh
C=skill/cypher/scripts/cypher.py
$C "Bears a Halo of Fire"            # a focus, with its tier abilities
$C "Onslaught" "Warrior"             # several at once; Warrior finds the type page too
$C "Blaster" --genre sci-fi          # limit to one genre's items
$C -s 'GM intrusion' -f rules        # full-text regex search
```

```sh
D=skill/dnd5e/scripts/dnd5e.py
$D "Fireball"                        # both editions, 2024 first
$D "Adult Red Dragon" -e 2014        # limit to one edition
$D "Grappled"                        # finds "Rules Glossary > Grappled"
$D -s 'opportunity attack' -f rules  # full-text regex search
```


## Discord bot

A Bun/TypeScript Discord bot in `bot/` (discord.js) answers `/pf <query>`, `/sf <query>`, `/hero <query>` and `/cypher <query>`. It reads the same data files as the skills and doesn't need Python.

`/pf` searches Pathfinder 2e. `/sf` searches Pathfinder 2e and Starfinder 2e together, and each result says which game it's from. `/hero` searches HERO System 6e and 5e together, 6e first, and also matches HERO Designer ids (e.g. `ENERGYBLAST`). Its results name the edition, the template (`Main6E`, `Vehicle6E`, ...) and the id. `/hero` is only registered if the HERO data has been extracted. Since that data is Hero Games' copyrighted material, only offer `/hero` on servers where that's appropriate. `/cypher` searches the Cypher System SRD. A type, flavor, descriptor or focus can be found by its bare name (e.g. `Warrior` finds `Type > Warrior`), and the dropdown tells apart same-named items from different genres. `/cypher` is only registered if the Cypher data has been extracted. Names autocomplete as you type. Results are private to the person who asked, with a **Share to channel** button to post them. When a query matches several records (including the same name in both games), a dropdown lets you switch between them. Long records page with ◀ ▶, and creatures with background text get a **Lore** button. If no name matches, the bot falls back to a full-text search and lists the hits. In `/hero`, the dropdown also lists the same ability's versions in other templates.

Setup:

1. Extract the data.
2. In the [Discord developer portal](https://discord.com/developers/applications), create an application, add a bot, and copy its token (from the **Bot** page, not the Public Key). No privileged intents are needed.
3. Invite it with `https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot+applications.commands&permissions=19456` (View Channels, Send Messages, Embed Links).
4. Register the slash commands with `--sync` (below) once, and again whenever the command definitions change or you add or remove the HERO or Cypher data. Global commands can take a while to appear. Set `GUILD_ID` in the env file to sync to a single server instantly while testing.

The bot loads all data into memory at startup, so restart the service after `./extract_pf2e.py`, `./extract_hero.py` or `./extract_cypher.py` updates the data.

### Bun

Requires [Bun](https://bun.sh) 1.x.

```sh
cd bot
bun install
cp .env.example .env && chmod 600 .env   # set DISCORD_TOKEN; Bun loads .env automatically

bun run sync     # register /pf, /sf, /hero and /cypher, then keep running (later runs: bun run start)
bun run start --verbose   # also log each interaction and gateway event to the console

bun src/bot.ts --preview "Red Dragon (Adult)"   # no Discord needed
bun src/bot.ts --preview "Laser Pistol" --sf   # same, for /sf
bun src/bot.ts --preview "Flight" --hero        # same, for /hero
bun src/bot.ts --preview "Warrior" --cypher     # same, for /cypher
bun test
bun run typecheck
```

To have `/hero` answer with only some editions, set `HERO_EDITIONS` in `.env` to a comma-separated list from `6e`, `5e` (default: both). Lookups, autocomplete, full-text search and the dropdown all skip the other editions.

Service: edit the paths and user in `bot/gaming-skills.service`, copy it to `/etc/systemd/system/`, then `sudo systemctl enable --now gaming-skills`.

## Layout

```
extract_pf2e.py               # release json-assets.zip -> compact text
extract_hero.py               # HERO Designer rules JSON -> compact text
extract_cypher.py             # cyphersystem-compendium release.zip (LevelDB packs) -> compact text
extract_dnd5e.py              # dnd5e system release zip (LevelDB packs, range-fetched) -> compact text
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
skill/cypher/
  SKILL.md                    # when Claude uses the skill; record format legend
  scripts/cypher.py           # lookup / search tool
  data/                       # generated, not committed (see .gitignore)
    VERSION                   # release tag
    *.txt                     # one file per category, plus index.txt
skill/dnd5e/
  SKILL.md                    # when Claude uses the skill; record format legend
  scripts/dnd5e.py            # lookup / search tool
  data/                       # generated, not committed (see .gitignore)
    VERSION                   # release tag
    2024/*.txt  2014/*.txt    # one file per category, plus index.txt
bot/
  src/bot.ts                  # Discord bot (discord.js): /pf, /sf, /hero and /cypher commands, components
  src/store.ts                # in-memory data, lookup/search/autocomplete (port of pf.py + hero.py + cypher.py)
  src/render.ts               # record -> Discord markdown pages
  test/                       # bun test
  gaming-skills.service       # sample systemd unit
```
