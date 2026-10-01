---
name: hero
description: HERO System (5th and 6th Edition; Champions, Fantasy Hero, etc.) character-building reference extracted from HERO Designer's own rules data. Use for ANY question about HERO System Powers, Advantages, Limitations, Adders, Skills, Skill Enhancers, Perks, Talents, Characteristics (costs, figured characteristics, NCM), Martial Arts maneuvers, Disadvantages/Complications, Languages and language similarity, Vehicle/Base/Automaton/AI/Computer build rules, or point costs and modifier values — instead of answering from memory.
---

# HERO System reference

All data lives under this skill's directory: `data/{6e,5e}/<category>.txt`, **one record per line**. It comes from HERO Designer's rules templates, so it covers what a character builder needs: every ability's cost structure, Adders, Advantages and Limitations with their values, option tables, and the short definition HERO Designer shows in its help pane. 5e definitions often cite the rulebook page. It does **not** hold the rulebooks' prose on combat, the Speed Chart, damage tables, Knockback, Range Modifiers, Presence Attacks and so on. If a question needs that, say the answer comes from general knowledge, not this data. The HERO Designer build it came from is in `data/VERSION`.

## How to look things up (use Bash)

`scripts/hero.py` is at this skill's base directory. Always call it with that absolute path.
- `scripts/hero.py "Name" ["Name2" ...]` prints full records with one field per line. It matches exact names (or exact `id`s, e.g. `ENERGYBLAST`) first, then prefixes, then substrings, case-insensitive. You can pass several names in one call. 6e results come before 5e.
- `scripts/hero.py -s 'regex'` runs a full-text search and lists matching record names with context. Use it for concepts or when you don't know the name.
- Options:
  - `-g 6e|5e`: limit to one edition. **Default to 6e** unless the user says 5e/5ER, names a 5e-only thing, or the context is clearly 5e.
  - `-f <category>`: limit to one file, e.g. `powers`, `modifiers`, `skills`.
  - `-t <system>`: limit to one HERO Designer template, e.g. `Main6E`, `Vehicle6E`, `Base`.
  - `-n N`: maximum number of results.
  - `-r`: raw single-line output.
- Don't use the Grep or Read tools on the data files. Some records are several KB on one line, and those tools truncate long lines. Plain `grep` through Bash is fine, e.g. `grep -i '^flight|' data/6e/powers.txt`.

Strategy:
1. For a named thing (Power, Advantage, Limitation, Skill, Talent, Perk, maneuver, Complication), run `hero.py "Name"`.
2. Names differ between editions, but the `id` stays the same. If a name misses (e.g. 6e renamed Energy Blast to Blast, Force Field to Resistant Protection, and Physical Limitation to Physical Complication), look it up in the other edition with `-g`, then look up its `id` in the edition you want. Example: `hero.py "Energy Blast" -g 5e` shows `id:ENERGYBLAST`, and `hero.py ENERGYBLAST -g 6e` finds Blast.
3. Advantages, Limitations and other modifiers that apply to any ability are in `modifiers`. Ones that apply to just one ability are inside that ability's record, under `mods:`.
4. Vehicles, Bases, Automatons, AIs and Computers are built with their own template. Their `systems` record (e.g. `hero.py Vehicle6E -f systems`) lists what the template removes and changes. Changed records appear under that template's name, after the `Main`/`Main6E` version, so read the right one.
5. For language similarity (how many points of familiarity a known language gives with another one), run `hero.py "Language" -f languages`.
6. Quote point costs and modifier values exactly as recorded, and say which edition you're quoting.

## Files per edition
`characteristics skills skill-enhancers martial-arts perks talents powers (includes senses and sense groups) modifiers disadvantages (6e Complications) languages systems index`

`index.txt` is `Name|kind system|file`.

## Record format
`Name|kind|system|id:XMLID|label:value|...|definition`

- `kind`:
  - `power`, `sense`, `sense group`, `skill`, `skill enhancer`, `perk`, `talent`, `maneuver`, `characteristic`, `language`, `system`.
  - `disadvantage` (5e) or `complication` (6e).
  - In `modifiers`: `advantage`, `limitation`, or `modifier` when the value can go either way.
- `system` is the HERO Designer template: `Main6E`/`Main` for normal characters, or a variant such as `Vehicle6E`, `Base6E`, `Automaton6E`, `AI6E`, `Computer6E`, `Heroic6E`.
- Empty fields are omitted.
- `N` in a name stands for a number the player chooses.
- ` / ` separates paragraphs.
- `¦` stands for a literal pipe.

Costs:
- `cost:B, +C per V` means B base points, then C more points for every V levels. Levels are whatever the ability buys: d6 of damage, meters, +1 to a roll, points of a characteristic.
- `lvls a..b` (or `a+`) is the allowed level range.
- `range x..y` is the allowed cost range when the cost is chosen. `min` is a minimum cost.
- Modifier values are written as HERO does: `+1/2`, `-1 1/4`.
- A multiplier is shown as `x2`.
- Skills: `roll:DEX 3, +2 per 1` means the skill is based on DEX, costs 3 points for the base roll (9 + characteristic/5), and costs 2 more per +1. `fam:8- for 1` is the cost of a Familiarity.
- Characteristics: `base` is the starting value. `figured:+1 PD per 5` (5e) gives the Figured Characteristics. `ncm` is the Normal Characteristic Maximum (5e). The `ncm40`/`ncm60`/`ncm10` labels hold the age-adjusted maxima.

Other labels:
- `type` is HERO Designer's category, e.g. `attack`, `defense`, `movement`, `adjustment`, `mental`, `sensory`, `standard`.
- `dur`, `tgt`, `rng`, `end`, `def`: duration (`instant`/`constant`/`persistent`/`inherent`), target (`dcv`, `ecv`, `hex`, `selfonly`), range (`yes`/`no`/`self`/`los`, or a number), whether it costs END, and the defense it works against.
- `does`: `damage`, `body`, `knockback`.
- `opt`, `adders` and `mods` are lists separated by `; `. Each item is written `Name (cost) [excl X] [req Y] {options} : definition`. `excl` and `req` name other ids that it excludes or requires.
- `ex` lists examples, `src` the source book(s) (5e), and `provides` the abilities a sense group gets by default.
- Maneuvers (`martial-arts`): `cost` is the maneuver's point cost, and `ocv`/`dcv` are its modifiers. `phase` is the action it takes. `dc` is the Damage Classes it adds. `effect` is the result, where `[NORMALDC]` means the attacker's damage, `[WEAPONDC]` means the weapon's damage, and `v/10` means velocity/10 (5e `v/5`). `cat` is `Hand To Hand` or `Ranged`.
- Languages: `family`, then `4pt`/`3pt`/`2pt`/`1pt` list the similar languages and how many points of familiarity knowing this one gives with each.
- Systems: `extends` names the parent template, and `sheet` the character-name label. `settings` holds HERO Designer's settings for the template. `removes` lists what the template drops from the parent, and `entries` what it adds or changes.

## Rebuilding
The data is generated by `extract_hero.py` in the ork-pf2e-tools repo. Its input is the rules directory written by `npx ork-hero-extract-rules /path/to/HD6.jar` (from the ork-hero-export-renderer package). To rebuild, run `./extract_hero.py [--rules DIR]` from that repo. The data is Hero Games' copyrighted material extracted from the user's own HERO Designer copy, so don't publish or redistribute it.
