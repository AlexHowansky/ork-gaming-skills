---
name: dnd5e
description: Dungeons & Dragons 5th Edition (D&D 5e) rules reference — both the 2024 rules (SRD 5.2, "5.5e"/"One D&D") and the 2014 rules (SRD 5.1) — extracted from the Foundry VTT dnd5e system. Use for ANY question about D&D 5e rules, spells, classes, subclasses, class features, species/races, backgrounds, feats, conditions, actions, combat, equipment, weapons and weapon mastery, armor, magic items, monsters and stat blocks, CR and XP, spell lists, the rules glossary, or roll tables — instead of answering from memory.
---

# D&D 5e reference

All data lives under this skill's directory in `data/2024/<category>.txt` (SRD 5.2) and `data/2014/<category>.txt` (SRD 5.1), **one record per line**. Source release tag: `data/VERSION`. The content is the System Reference Document plus the Free Rules material bundled with the system (the 2024 basic rules chapters and the species, class, background and monster appendices). It is not the full Player's Handbook, Monster Manual or Dungeon Master's Guide. If something isn't found, it may not be in this material. Say so rather than guessing.

## How to look things up (use Bash)

`scripts/dnd5e.py` is at this skill's base directory. Always call it with that absolute path.
- `scripts/dnd5e.py "Name" ["Name2" ...]` prints full records with one field per line. It matches exact names first, then prefixes, then substrings, case-insensitive. For `Journal > Page` records an exact match on the page name alone also counts, so `Grappled` finds `Rules Glossary > Grappled`. You can pass several names in one call. 2024 records are listed before 2014.
- `scripts/dnd5e.py -s 'regex'` runs a full-text search and lists matching record names with context. Use it for concepts or when you don't know the name.
- Options:
  - `-e 2024` or `-e 2014`: limit to one edition.
  - `-f <category>`: limit to one file, e.g. `spells`, `monsters`, `rules`, `class-features`.
  - `-n N`: maximum number of results.
  - `-r`: raw single-line output.
- Don't use the Grep or Read tools on the data files. Rules pages can be 20+ KB on a single line, and those tools truncate long lines. Plain `grep` through Bash is fine, e.g. `grep -i '^fireball|' data/2024/spells.txt`.

Strategy:
1. Work out which edition the user means. Default to 2024 unless they say 2014, "5e legacy", or use 2014-only terms (race, subrace, "Monster Manual 2014"). Many names exist in both editions with different rules, so always say which edition you're quoting. If the edition is unclear and the two differ, give both.
2. For a named thing (spell, monster, feat, item, class feature, condition), run `dnd5e.py "Name"`.
3. For a class, look up the class record (the `features` label lists features by level), then look up the features themselves in `class-features`. Subclass features are in `class-features` too, and the `granted` label shows `Subclass Level`.
4. For general rules, run `dnd5e.py -s 'topic' -f rules`, then `dnd5e.py "Journal > Page"`. The 2024 `Rules Glossary > *` pages and the 2014 `Appendix A: Conditions > *` pages define conditions and game terms. `Appendix D: Rule References > *` (2024) has short definitions too.
5. For a 2024 monster's background, habitat, treasure and lair, run `dnd5e.py "Name" -f monster-lore`. Lore is only searched when you name that file.
6. 2024 renames: race → species, and the background now grants the ability score increases and an origin feat. Attacks are written `Melee Attack Roll: +5`, saves as `Dexterity Saving Throw: DC 13`.

## Files
Per edition: `spells spell-lists classes subclasses class-features species backgrounds feats equipment monsters monster-features rules tables index`. 2024 also has `vehicles` and `monster-lore` (opt-in; searched only with `-f monster-lore`).

`index.txt` is `Name|kind|file`.

## Record format
`Name|kind|label:value|...|text`

- `kind`:
  - `spell`, `spell list`, `lore`, `class`, `subclass`, `feature` (class, subclass, species, background and monster features), `feat`, `species`, `background`, `weapon`, `armor`, `gear`, `consumable`, `tool`, `loot`, `container`, `monster`, `vehicle`, `table`.
  - In `rules`: `condition` and `rule` for glossary entries, and `rules` for everything else.
- Empty fields are omitted.
- ` / ` separates paragraphs and list items. `/[Heading]/` marks a heading inside a page. In tables, `,` separates cells and `;` separates rows.
- `¦` stands for a literal pipe.

Labels:
- Spells: `level` (`cantrip` or 1–9), `school`, `time`, `range`, `components`, `duration`, `classes` (class spell lists), `subclasses` (subclass and domain lists that include it).
- Classes: `hd`, `primary` (2024), `spellcasting` (progression and ability), `features` (`level: names; ...`), `scale` (class table columns such as Rages, Sneak Attack, Martial Arts Die as `level value` pairs). The text holds the proficiencies, hit points and starting equipment.
- Features and feats: `type` (e.g. `Feat (Origin)`, `Class Feature (Channel Divinity)`), `granted` (the class or subclass and level), `requires`, `prerequisite`, `repeatable`, `uses` (e.g. `2/Long Rest`, `Recharge 5–6`), `activation`.
- Species: `type`, `size`, `speed`, `senses`, `traits`. Backgrounds: `grants` (the origin feat or feature). In 2024 the text lists ability scores, feat, skills, tool and equipment.
- Equipment: `type`, `damage`, `versatile`, `properties`, `mastery` (2024), `range`, `ac`, `strength` (required Strength), `bonus` (magic), `rarity`, `attunement`, `uses`/charges, `price`, `weight`.
- Monsters: `tag` (size, type, alignment), `ac`, `initiative` (2024), `hp`, `speed`, `abilities` (score and modifier), `saves` (proficient saves only), `skills`, `vulnerabilities`, `resistances`, `immunities`, `condition-immunities` (2014; 2024 folds them into `immunities`), `gear`, `senses`, `languages`, `cr` (with XP and PB), `habitat`, `treasure`. The text holds `/[Traits]/ /[Actions]/ /[Bonus Actions]/ /[Reactions]/ /[Legendary Actions]/` with each entry as `Name (uses). text`. Attack bonuses, damage and save DCs are computed from the stat block, as Foundry shows them.
- Rules pages: `book` is the folder the journal sits in.
- Spell lists: `class` or `subclass`, then `Cantrips: ...; Level 1: ...`.
- Tables: `roll` is the formula, followed by `range:result` entries separated by `; `.

## Rebuilding
The data is generated by `extract_dnd5e.py` in the ork-gaming-skills repo from the compendium packs in the foundryvtt/dnd5e system release. Run `./extract_dnd5e.py --check` to see if a newer release exists, and `./extract_dnd5e.py` to rebuild. The SRD 5.1 and SRD 5.2 are © Wizards of the Coast, licensed under CC-BY-4.0. The Free Rules pages are Wizards of the Coast material that isn't CC-BY. The generated data is for local use and isn't committed to the repo.
