---
name: cypher
description: Cypher System (Cypher SRD) rules reference extracted from the cyphersystem-compendium Foundry module. Use for ANY question about Cypher System rules, character types, flavors, descriptors, foci, abilities and their costs, skills and inabilities, Effort, Edge, Pools, difficulty and task levels, GM intrusions, XP, cyphers, artifacts, equipment, weapons, armor, creatures and NPCs, vehicles and starships, power shifts, or the genre rulebooks (fantasy, modern fantasy, sci-fi, horror, superhero, post-apocalyptic, fairy tale) — instead of answering from memory.
---

# Cypher System reference

All data lives under this skill's directory: `data/<category>.txt`, **one record per line**. It holds the whole Cypher System Reference Document, including the expanded genre rulebooks. Source release tag: `data/VERSION`.

## How to look things up (use Bash)

`scripts/cypher.py` is at this skill's base directory. Always call it with that absolute path.
- `scripts/cypher.py "Name" ["Name2" ...]` prints full records with one field per line. It matches exact names first, then prefixes, then substrings, case-insensitive. For `Journal > Page` records an exact match on the page name alone also counts, so `Warrior` finds `Type > Warrior`. You can pass several names in one call.
- `scripts/cypher.py -s 'regex'` runs a full-text search and lists matching record names with context. Use it for concepts or when you don't know the name.
- Options:
  - `-f <category>`: limit to one file, e.g. `abilities`, `rules`, `creatures`, `cyphers`.
  - `--genre <genre>`: limit to one genre's items: `fantasy`, `modern`, `modern-fantasy`, `sci-fi`, `horror`, `post-apocalyptic`, `fairy-tale`, `superhero`, `power-boost`.
  - `-n N`: maximum number of results.
  - `-r`: raw single-line output.
- Don't use the Grep or Read tools on the data files. Rules pages can be 20+ KB on a single line, and those tools truncate long lines. Plain `grep` through Bash is fine, e.g. `grep -i '^onslaught|' data/abilities.txt`.

Strategy:
1. For a named thing (ability, cypher, artifact, creature, item, skill), run `cypher.py "Name"`.
2. For character options, look up the type, flavor, descriptor or focus by name (`Warrior`, `Stealth Flavor`, `Charming`, `Bears a Halo of Fire`). The record lists the tier abilities by name. Look those up in `abilities` for their costs and text.
3. For general rules, run `cypher.py -s 'topic' -f rules`, then `cypher.py "Journal > Page"`. Examples:
   - `Rules of the Game` (task difficulty, Effort, Edge, damage track, distances)
   - `Rules of the Game > Action: Attack`
   - `Experience Points`
   - `Cyphers` (cypher limits and subtle/manifest cyphers)
   - `Creatures and NPCs`
   - `Fantasy Rulebook > Magical Rules Modules`
   The `Cypher System Rulebook Index > *` pages are tables of contents and help you find the right page.
4. A creature's target number is its level × 3 (shown as `level:4 (target 12)`).
5. Several genres can have an item with the same name. The `genre` label says which one. Say which genre you're quoting.

## Files
`abilities skills cyphers artifacts equipment weapons armor creatures vehicles power-shifts rules tables index`

`index.txt` is `Name|kind|file`.

## Record format
`Name|kind|label:value|...|text`

- `kind`:
  - `ability`, `skill`, `inability`, `cypher`, `artifact`, `equipment`, `material`, `ammo`, `weapon`, `armor`, `power shift`, `creature`, `vehicle`, `starship`, `table`.
  - In `rules`: `type`, `flavor`, `descriptor`, `focus` and `ability` (ability category pages) for character options, and `rules` for everything else.
- Empty fields are omitted.
- ` / ` separates paragraphs and list items. `/[Heading]/` marks a heading inside a rules page.
- `¦` stands for a literal pipe.

Labels:
- Abilities: `cost:3 Intellect` is the Pool cost. A `+` (e.g. `2+ Intellect`) means the cost can go higher. If there's no cost, the ability is free or an enabler. `pack` says where it came from when that isn't the main abilities list (`cantrips`, `mutations`, `descriptor-characteristics`, `posthuman-packages-sci-fi`).
- Skills: `rating` is `trained`, `specialized`, `practiced`, or `inability`. `pack` is `basic-skills`, `expanded-skills`, or `inabilities`.
- Cyphers and artifacts: `level` is the level roll, e.g. `1d6+2`. `depletion` is the artifact's depletion chance, e.g. `1 in 1d20`.
- Equipment: `level`, `price` (`inexpensive`, `moderate`, `expensive`, `very expensive`, `exorbitant`), `qty`.
- Weapons: `weapon` is `light`/`medium`/`heavy`, then `damage`, `range`, `notes`. Armor: `armor` is `light`/`medium`/`heavy`, then `rating`, `cost` (extra Speed Effort cost), `notes`.
- Creatures: `level`, `health`, `damage` (points inflicted), `armor`, `pack` (`creatures`, `basic-creatures-and-npcs`, `npcs`, `supervillains`). The text holds Motive, Environment, Movement, Modifications, Combat, Interaction, Use, Loot and GM intrusion.
- Vehicles and starships: `level`, `crew`, `weapons` (weapon systems).
- Rules pages: `book` is the folder the journal sits in, e.g. `Cypher System Rulebook > Part 2: Rules`.
- Tables: `roll` is the formula, followed by `range:result` entries separated by `; `.

## Rebuilding
The data is generated by `extract_cypher.py` in the ork-gaming-skills repo from the `release.zip` of the mrkwnzl/cyphersystem-compendium Foundry module. Run `./extract_cypher.py --check` to see if a newer release exists, and `./extract_cypher.py` to rebuild. The content is Monte Cook Games' Cypher System material, used under the Cypher System Open License.
