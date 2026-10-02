/**
 * Turn a compact record line into Discord markdown pages.
 *
 * PF2e/SF2e record format (see skill/pf2e/SKILL.md):
 *   Name|kind level|SRC [R]|label:value|...|description
 * HERO System record format (see skill/hero/SKILL.md):
 *   Name|kind|system|id:XMLID|label:value|...|definition
 * Cypher System record format (see skill/cypher/SKILL.md):
 *   Name|kind|label:value|...|text
 * D&D 5e record format (see skill/dnd5e/SKILL.md):
 *   Name|kind|label:value|...|text
 */
import type { Rec } from "./store";

/** Lookup table without Object.prototype keys, so e.g. a "constructor" trait isn't found. */
function dict<T>(o: Record<string, T>): Record<string, T> {
  return Object.assign(Object.create(null), o);
}

export const PAGE = 4000; // embed description limit is 4096
export const COLORS: Record<string, number> = dict({
  pf2e: 0x5d0000, sf2e: 0x1f6fb2, "6e": 0xc9a227, "5e": 0x7a5c12, cypher: 0x2a9d8f,
  dnd2024: 0xe40712, dnd2014: 0x8b1a10,
});
export const GAME_NAMES: Record<string, string> = dict({
  pf2e: "Pathfinder 2e", sf2e: "Starfinder 2e", "6e": "HERO System 6e", "5e": "HERO System 5e",
  cypher: "Cypher System", dnd2024: "D&D 5e (2024)", dnd2014: "D&D 5e (2014)",
});
export const GAME_TAGS: Record<string, string> = dict({
  pf2e: "PF2e", sf2e: "SF2e", "6e": "6e", "5e": "5e", cypher: "Cypher", dnd2024: "D&D 2024", dnd2014: "D&D 2014",
});
const HERO_GAMES = new Set(["6e", "5e"]);

const ACTIONS: Record<string, string> = dict({ "1a": "◆", "2a": "◆◆", "3a": "◆◆◆", r: "⟲", f: "◇", "0": "◇" });
const LETTER_ACTIONS: Record<string, string> = dict({ A: "◆", D: "◆◆", T: "◆◆◆", R: "⟲", F: "◇" });

const LABELS: Record<string, string> = dict({
  tr: "Traits", act: "Actions", cast: "Cast", trad: "Traditions",
  rng: "Range", area: "Area", tgt: "Targets", def: "Defense", dur: "Duration",
  prereq: "Prerequisites", req: "Requirements", trig: "Trigger", freq: "Frequency",
  price: "Price", bulk: "Bulk", usage: "Usage", cat: "Category", dmg: "Damage",
  dexcap: "Dex Cap", chk: "Check Penalty", spd: "Speed", str: "Strength",
  hard: "Hardness", hp: "HP", perc: "Perception", lang: "Languages",
  skills: "Skills", imm: "Immunities", weak: "Weaknesses", res: "Resistances",
  gear: "Items", ab: "", spells: "Spells", stealth: "Stealth", disable: "Disable",
  routine: "Routine", reset: "Reset", desc: "Description", blurb: "",
  key: "Key Attribute", saves: "Saves", atk: "Attacks", features: "Features",
  boost: "Attribute Boosts", flaw: "Attribute Flaw", anc: "Ancestry",
  sanct: "Sanctification", font: "Divine Font", attr: "Divine Attribute",
  skill: "Divine Skill", weapon: "Favored Weapon", dom: "Domains",
  altdom: "Alternate Domains", reload: "Reload", ac: "AC", crew: "Crew",
  passengers: "Passengers", uses: "Uses", level: "Level", size: "Size",
  vision: "Vision", speed: "Speed", cost: "Cost", ritual: "Ritual",
  feat: "Feat", feats: "Feats", spellcasting: "Spellcasting",
});
const HIDDEN = new Set(["pack"]);
const SIZES: Record<string, string> = dict({ tiny: "Tiny", sm: "Small", med: "Medium", lg: "Large", huge: "Huge", garg: "Gargantuan" });
const RANKS: Record<string, string> = dict({ C: "Cantrips", "1": "1st", "2": "2nd", "3": "3rd" });
const ATTRS = ["str", "dex", "con", "int", "wis", "cha"];
const COMMA_LISTS = new Set(["perc", "skills", "lang", "imm", "weak", "res", "spd", "gear", "trad", "dom", "altdom", "attr"]);

const SRC_RE = /^([^\s:|]+)( R)?$/;
const LABEL_RE = /^([a-z]{1,12}):(.*)$/s;
const ATTR_RE = /^(?:(?:cha|con|dex|int|str|wis)[+-]\d+ ?)+$/;
const KEYWORD_RE = new RegExp(
  "^(Critical Success|Critical Failure|Success|Failure|Trigger|Requirements?|Effect|Frequency" +
    "|Saving Throw|Maximum Duration|Onset|Stage \\d+|Heightened \\([^)]*\\)|Activate|Craft Requirements" +
    "|Special|Cost|Access|Amp(?: Heightened \\([^)]*\\))?|Prerequisites|Religious Symbol" +
    "|Sacred Animal|Sacred Colors|Areas|Edicts|Anathema|Follower Alignments)(?=[\\s:]|$):?",
);

export type Rendered = {
  game: string;
  stem: string;
  name: string;
  kind: string;
  source: string;
  remaster: boolean;
  xmlid: string; // HERO Designer id, shown in the footer
  pages: string[];
};

/** Python's str.partition. */
function partition(s: string, sep: string): [string, string, string] {
  const i = s.indexOf(sep);
  return i < 0 ? [s, "", ""] : [s.slice(0, i), sep, s.slice(i + sep.length)];
}

/** Python's str.capitalize. */
function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

export function glyph(code: string): string {
  return ACTIONS[code] ?? code;
}

/** Replace [1a]/[r]/... tokens and 'Activate A' style Foundry letters with action glyphs. */
export function glyphs(text: string): string {
  text = text.replace(/\[(1a|2a|3a|r|f|0)\]/g, (_, c: string) => ACTIONS[c]!);
  return text.replace(/\bActivate ([ADTRF])\b/g, (_, c: string) => "Activate " + LETTER_ACTIONS[c]);
}

/** Escape characters Discord would treat as markdown; the data has no markdown of its own. */
export function esc(text: string): string {
  return text.replaceAll("¦", "|").replace(/([\\*_~`|>])/g, "\\$1");
}

function traits(value: string): string {
  return value
    .split(",")
    .map((t) => `\`${(SIZES[t] ?? t).toUpperCase()}\``)
    .join(" ");
}

function ordinal(r: string): string {
  if (r in RANKS) return RANKS[r]!;
  return /^\d+$/.test(r) ? `${r}th` : r;
}

/** 'Arcane Innate Spells DC35 atk+27: 4 Suggestion; C Detect Magic' -> readable lines. */
function spells(value: string): string {
  const lines: string[] = [];
  for (const entry of value.split(" // ")) {
    const [head, sep, body] = partition(entry, ": ");
    if (!sep) {
      lines.push(esc(entry));
      continue;
    }
    const m = /^(.*?)((?: DC\d+)?(?: atk[+-]\d+)?)$/.exec(head)!;
    const title = m[1]!;
    const stats = m[2]!.replace(/DC(\d+)/g, "DC $1").replace(/atk([+-]\d+)/g, "attack $1").trim();
    const ranks = body.split("; ").map((chunk) => {
      const [rank, , names] = partition(chunk, " ");
      return /^(?:C|\d+)$/.test(rank) ? `**${ordinal(rank)}** ${esc(names.replaceAll(",", ", "))}` : esc(chunk);
    });
    lines.push(`**${esc(title)}** ${stats}; ` + ranks.join("; "));
  }
  return lines.join("\n");
}

/** 'Name [2a] (traits) text / more' -> bold name, glyph, traits, paragraphs. */
function ability(value: string): string {
  let name: string, act: string, tr: string | undefined, rest: string;
  const m = /^(.+?) (\[(?:1a|2a|3a|r|f|0)\])(?: \(([^)]*)\))?(?: (.*))?$/s.exec(value);
  if (!m) {
    const m2 = /^([^()]+?) \(([^)]*)\)(?: (.*))?$/s.exec(value);
    if (m2 && m2[1]!.length <= 40) {
      [name, act, tr, rest] = [m2[1]!, "", m2[2], m2[3] ?? ""];
    } else {
      return "• " + paragraphs(value);
    }
  } else {
    [name, act, tr, rest] = [m[1]!, glyphs(m[2]!), m[3], m[4] ?? ""];
  }
  let head = `• **${esc(name)}**`;
  if (act) head += ` ${act}`;
  if (tr) head += ` (${esc(tr.replaceAll(",", ", "))})`;
  return head + (rest ? " " + paragraphs(rest) : "");
}

function defenses(value: string): string {
  return esc(value)
    .replace(/^AC(\d+)/, "**AC** $1")
    .replace(/\bF([+-]\d+)/g, "**Fort** $1")
    .replace(/\bR([+-]\d+)/g, "**Ref** $1")
    .replace(/\bW([+-]\d+)/g, "**Will** $1")
    .replace(/\bhard(\d+)/g, "**Hardness** $1")
    .replace(/\bHP(\d+)/g, "**HP** $1");
}

function attributes(value: string): string {
  const mods = new Map<string, string>();
  for (const m of value.matchAll(/(cha|con|dex|int|str|wis)([+-]\d+)/g)) mods.set(m[1]!, m[2]!);
  return ATTRS.filter((a) => mods.has(a))
    .map((a) => `**${capitalize(a)}** ${mods.get(a)}`)
    .join(" ");
}

function strike(value: string): string {
  const [kind, , raw] = partition(value, " ");
  const rest = glyphs(esc(raw))
    .replace(/\brng(\d+)/g, "range $1 ft.")
    .replace(/\(([^)]*)\)/, (_, inner: string) => "(" + inner.replaceAll(",", ", ") + ")");
  return `**${capitalize(kind)}** ${rest}`;
}

/**
 * A row's cells. `strict` is for data whose cell text has commas too: those are followed by a space
 * (or are thousands separators), cell boundaries aren't.
 */
function cells(row: string, strict = false): string[] {
  return strict ? row.split(/,(?! |\d{3}(?!\d))/) : row.split(",");
}

/** `strict`: every row has the same number of cells (see cells()). */
function isTable(par: string, strict = false): boolean {
  const rows = par.split("; ");
  if (rows.length < 3) return false;
  if (strict) {
    const n = cells(rows[0]!, true).length;
    return n > 1 && rows.every((r) => cells(r, true).length === n && r.length < 100);
  }
  return rows.slice(0, 3).every((r) => r.includes(",") && r.length < 60 && !r.includes(". "));
}

function table(par: string, strict = false): string {
  const rows = par.split("; ").map((r) => cells(r, strict));
  const multi = rows.filter((r) => r.length > 1);
  const width = Math.max(...multi.map((r) => r.length));
  const widths = Array.from({ length: width }, (_, i) =>
    Math.max(0, ...multi.filter((r) => i < r.length).map((r) => r[i]!.length)),
  );
  const out = rows.map((r) =>
    r.length === 1 ? r[0]! : r.map((c, i) => c.padEnd(widths[i]!)).join("  ").trimEnd(),
  );
  const body = out.join("\n").replaceAll("`", "'").replaceAll("¦", "|");
  return "```\n" + body + "\n```";
}

/**
 * A table whose cells can hold commas (and '; '): at least 3 'first cell,rest' rows, starting with one
 * and making up most of the paragraph.
 */
function isRows(par: string): boolean {
  const r = par.split("; ");
  const n = r.filter((row) => row.includes(",")).length;
  return r[0]!.includes(",") && n >= 3 && n * 3 >= r.length * 2;
}

/** Such a table as one line per row, first cell in bold. */
function rows(par: string): string {
  return par
    .split("; ")
    .map((row) => {
      const [first, sep, rest] = partition(row, ",");
      return sep ? `**${esc(first)}** ${esc(rest)}` : esc(row);
    })
    .join("\n");
}

/** One paragraph; `keywords` bolds PF2e lead-ins like 'Effect' and 'Special'. */
function paragraph(par: string, keywords = true, strictTables = false): string {
  par = par.trim();
  if (!par) return "";
  const m = /^\[([^\]]+)\]$/.exec(par);
  if (m) return `__**${esc(m[1]!)}**__`;
  if (isTable(par, strictTables)) return table(par, strictTables);
  if (strictTables && isRows(par)) return rows(par);
  let text = glyphs(esc(par));
  const k = keywords ? KEYWORD_RE.exec(text) : null;
  if (k) text = `**${k[0].replace(/:+$/, "")}**` + text.slice(k[0].length);
  return text;
}

function paragraphs(text: string, keywords = true, strictTables = false): string {
  text = text.replace(/\s*\/\[([^\]]+)\]\/\s*/g, " / [$1] / ");
  return text
    .split(" / ")
    .map((p) => paragraph(p, keywords, strictTables))
    .filter((p) => p)
    .join("\n");
}

function fieldLine(label: string, value: string): string {
  if (label === "tr") return traits(value);
  if (label === "act" || label === "cast") return `**${LABELS[label]}** ${glyph(value)}`;
  if (label === "spells" && (value.includes(" DC") || value.includes(": "))) return spells(value);
  if (label === "ab") return ability(value);
  if (label === "blurb") return `*${esc(value)}*`;
  const name = LABELS[label] ?? capitalize(label);
  const v = COMMA_LISTS.has(label) ? value.replaceAll(",", ", ") : value;
  if (label === "features") return `**${name}**\n` + v.split("; ").map(esc).join("\n");
  return `**${name}** ${paragraphs(v)}`;
}

function parse(rec: Rec): [Rendered, string[]] {
  const [game, stem, line] = rec;
  const parts = line.split("|");
  const r: Rendered = {
    game, stem,
    name: parts[0]!.replaceAll("¦", "|"),
    kind: parts.length > 1 ? parts[1]! : "",
    source: "", remaster: false, xmlid: "", pages: [],
  };
  let rest = parts.slice(2);
  const m = rest.length > 1 ? SRC_RE.exec(rest[0]!) : null;
  if (m) {
    r.source = m[1]!;
    r.remaster = Boolean(m[2]);
    rest = rest.slice(1);
  }
  return [r, rest];
}

function blocks(rest: string[]): string[] {
  const out: string[] = [];
  for (const p of rest) {
    const m = LABEL_RE.exec(p);
    if (m && (m[1]! in LABELS || HIDDEN.has(m[1]!) || m[2]!.length < 200)) {
      if (HIDDEN.has(m[1]!)) continue;
      out.push(fieldLine(m[1]!, m[2]!));
    } else if (ATTR_RE.test(p)) out.push(attributes(p));
    else if (/^(AC|HP)\d/.test(p)) out.push(defenses(p));
    else if (/^(melee|ranged) /.test(p)) out.push(strike(p));
    else out.push(paragraphs(p));
  }
  return out;
}

/** Pack lines into pages of at most `size` characters, splitting overlong lines on words. */
export function paginate(chunks: string[], size = PAGE): string[] {
  const pages: string[] = [];
  let cur = "";
  for (let line of chunks.flatMap((c) => c.split("\n"))) {
    while (line.length > size) {
      let cut = line.lastIndexOf(" ", size - 1);
      cut = cut > Math.floor(size / 2) ? cut : size;
      const piece = line.slice(0, cut);
      line = line.slice(cut).trimStart();
      if (cur) {
        pages.push(cur);
        cur = "";
      }
      pages.push(piece);
    }
    if (cur.length + line.length + 1 > size) {
      pages.push(cur);
      cur = line;
    } else {
      cur = cur ? `${cur}\n${line}` : line;
    }
  }
  if (cur) pages.push(cur);
  const fixed = fixCodeBlocks(pages);
  return fixed.length ? fixed : [""];
}

/** Close and reopen ``` fences that a page break split. */
function fixCodeBlocks(pages: string[]): string[] {
  let carry = false;
  return pages.map((p) => {
    if (carry) p = "```\n" + p;
    carry = p.split("```").length % 2 === 0;
    if (carry) p += "\n```";
    return p;
  });
}

export function render(rec: Rec): Rendered {
  if (HERO_GAMES.has(rec[0])) return renderHero(rec);
  if (rec[0] === "cypher") return renderCypher(rec);
  if (DND_GAMES.has(rec[0])) return renderDnd(rec);
  const [r, rest] = parse(rec);
  const header = r.kind ? `*${esc(r.kind.charAt(0).toUpperCase() + r.kind.slice(1))}*` : "";
  // traits first; stable otherwise
  const ordered = [...rest].sort((a, b) => Number(!a.startsWith("tr:")) - Number(!b.startsWith("tr:")));
  r.pages = paginate([...(header ? [header] : []), ...blocks(ordered)]);
  return r;
}

export function footer(r: Rendered, sources?: Map<string, string>, page = 0): string {
  const bits = [GAME_NAMES[r.game] ?? r.game];
  if (r.source) {
    const title = sources?.get(r.source);
    bits.push(title ? `${title} (${r.source})` : r.source);
  }
  if (r.remaster) bits.push("Remaster");
  if (r.xmlid) bits.push(r.xmlid);
  if (r.pages.length > 1) bits.push(`Page ${page + 1}/${r.pages.length}`);
  return bits.join(" · ");
}

// HERO System

const HERO_LABELS: Record<string, string> = dict({
  type: "Type", cost: "Cost", dur: "Duration", tgt: "Target", rng: "Range", end: "END",
  def: "Defense", does: "Does", visible: "Visible", killing: "Killing", opt: "Options",
  adders: "Adders", mods: "Modifiers", excl: "Excludes", req: "Requires", ex: "Examples",
  src: "Source", provides: "Provides", roll: "Roll", fam: "Familiarity", base: "Base",
  figured: "Figured", ncm: "NCM", cat: "Category", ocv: "OCV", dcv: "DCV", phase: "Phase",
  dc: "DC", effect: "Effect", "weapon effect": "Weapon Effect", family: "Family",
  "4pt": "4 pts", "3pt": "3 pts", "2pt": "2 pts", "1pt": "1 pt", extends: "Extends",
  sheet: "Sheet", settings: "Settings", removes: "Removes", entries: "Entries",
});
const HERO_HIDDEN = new Set(["id", "adderseparator", "abbreviation", "wgabbreviation", "optionlabel", "showoption",
  "showinputinparens", "displaylevelsonly"]);
const HERO_LISTS = new Set(["opt", "adders", "mods", "ex", "removes", "entries"]); // '; '-separated
const HERO_LABEL_RE = /^([a-z0-9][a-z0-9 ]{0,23}):(.*)$/s;
const HERO_LINE = 100; // short fields share a line up to about this long

/** Split on '; ' outside (), [] and {}: option lists nest inside items. */
function splitList(value: string): string[] {
  const items: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < value.length; i++) {
    const c = value[i]!;
    if ("([{".includes(c)) depth++;
    else if (")]}".includes(c)) depth = Math.max(0, depth - 1);
    else if (depth === 0 && value.startsWith("; ", i)) {
      items.push(value.slice(start, i));
      start = i + 2;
    }
  }
  items.push(value.slice(start));
  return items.filter((x) => x);
}

/** 'Name (cost) [excl X] {options}: definition' -> bullet with the name in bold. */
function heroItem(item: string): string {
  const name = /^(.+?)(?= [(\[{]|: |$)/s.exec(item)![1]!;
  const rest = item.slice(name.length);
  return rest ? `• **${esc(name)}**${esc(rest)}` : `• ${esc(item)}`;
}

function heroLabel(label: string, optLabel: string): string {
  if (label === "opt" && optLabel) return optLabel;
  return HERO_LABELS[label] ?? label.charAt(0).toUpperCase() + label.slice(1);
}

function heroBlocks(rest: string[]): string[] {
  const out: string[] = [];
  const short: string[] = [];
  const optLabel = rest.find((p) => p.startsWith("optionlabel:"))?.slice("optionlabel:".length) ?? "";
  const flush = () => {
    let line = "";
    for (const s of short) {
      if (line && line.length + s.length + 3 > HERO_LINE) {
        out.push(line);
        line = s;
      } else line = line ? `${line} · ${s}` : s;
    }
    if (line) out.push(line);
    short.length = 0;
  };
  for (const p of rest) {
    const m = HERO_LABEL_RE.exec(p);
    if (!m) {
      flush();
      out.push(p.split(" / ").map((x) => x.trim()).filter((x) => x).map(esc).join("\n"));
      continue;
    }
    const [, label, value] = m as unknown as [string, string, string];
    if (HERO_HIDDEN.has(label)) continue;
    const name = esc(heroLabel(label, optLabel));
    if (HERO_LISTS.has(label) && value.length > 60) {
      flush();
      out.push(`**${name}**\n` + splitList(value).map(heroItem).join("\n"));
    } else if (value.length <= 40) short.push(`**${name}** ${esc(value)}`);
    else {
      flush();
      out.push(`**${name}** ${esc(value)}`);
    }
  }
  flush();
  return out;
}

function renderHero(rec: Rec): Rendered {
  const [game, stem, line] = rec;
  const parts = line.split("|");
  const r: Rendered = {
    game, stem,
    name: parts[0]!.replaceAll("¦", "|"),
    kind: parts[1] ?? "",
    source: parts[2] ?? "", remaster: false, xmlid: "", pages: [],
  };
  const rest = parts.slice(3);
  r.xmlid = rest.find((p) => p.startsWith("id:"))?.slice(3) ?? "";
  const header = r.kind ? `*${esc(r.kind.charAt(0).toUpperCase() + r.kind.slice(1))}*` : "";
  r.pages = paginate([...(header ? [header] : []), ...heroBlocks(rest)]);
  return r;
}

// Cypher System

const CYPHER_LABELS: Record<string, string> = dict({
  cost: "Cost", rating: "Rating", level: "Level", depletion: "Depletion", price: "Price", qty: "Quantity",
  weapon: "Weapon", damage: "Damage", range: "Range", notes: "Notes", armor: "Armor", health: "Health",
  crew: "Crew", weapons: "Weapon Systems", roll: "Roll",
});
// shown in the footer instead (genre, book) or only used to tell records apart (pack)
const CYPHER_FOOTER = new Set(["genre", "book"]);
const CYPHER_LABEL_RE = /^([a-z]{1,12}):(.*)$/s;
// 'Motive:', 'GM intrusion:', 'Tier 1:' lead-ins of creature and character option paragraphs
const LEAD_RE = /^([A-Z][A-Za-z0-9’' -]{0,30}):(?=\s)/;

function cypherParagraphs(text: string): string {
  return paragraphs(text, false)
    .split("\n")
    .map((line) => line.replace(LEAD_RE, "**$1:**"))
    .join("\n");
}

/** A table's '1-2:Result; 3:Result' entries, one per line. */
function rollTable(value: string): string {
  return value
    .split("; ")
    .map((e) => {
      const m = /^(\d+(?:-\d+)?):(.*)$/s.exec(e);
      return m ? `**${m[1]}** ${esc(m[2]!)}` : esc(e);
    })
    .join("\n");
}

function renderCypher(rec: Rec): Rendered {
  const [game, stem, line] = rec;
  const parts = line.split("|");
  const r: Rendered = {
    game, stem,
    name: parts[0]!.replaceAll("¦", "|"),
    kind: parts[1] ?? "",
    source: "", remaster: false, xmlid: "", pages: [],
  };
  const short: string[] = [];
  const body: string[] = [];
  for (const p of parts.slice(2)) {
    const m = CYPHER_LABEL_RE.exec(p);
    if (m && m[1] === "pack") continue;
    if (m && CYPHER_FOOTER.has(m[1]!)) r.source = m[2]!;
    else if (m && m[1]! in CYPHER_LABELS) short.push(`**${CYPHER_LABELS[m[1]!]}** ${esc(m[2]!)}`);
    else if (r.kind === "table" && /^\d+(-\d+)?:/.test(p)) body.push(rollTable(p));
    else body.push(cypherParagraphs(p));
  }
  const header = r.kind ? `*${esc(r.kind.charAt(0).toUpperCase() + r.kind.slice(1))}*` : "";
  r.pages = paginate([...(header ? [header] : []), ...(short.length ? [short.join(" · ")] : []), ...body]);
  return r;
}

// D&D 5e

const DND_GAMES = new Set(["dnd2024", "dnd2014"]);
const DND_LABELS: Record<string, string> = dict({
  level: "Level", school: "School", time: "Casting Time", range: "Range", components: "Components",
  duration: "Duration", classes: "Classes", subclasses: "Subclasses", hd: "Hit Die", primary: "Primary Ability",
  spellcasting: "Spellcasting", features: "Features", scale: "Class Table", type: "Type", granted: "Granted",
  requires: "Requires", prerequisite: "Prerequisite", repeatable: "Repeatable", uses: "Uses",
  activation: "Activation", size: "Size", speed: "Speed", senses: "Senses", traits: "Traits", grants: "Grants",
  damage: "Damage", versatile: "Versatile", properties: "Properties", mastery: "Mastery", ac: "AC",
  strength: "Strength", bonus: "Bonus", rarity: "Rarity", attunement: "Attunement", price: "Price",
  weight: "Weight", initiative: "Initiative", hp: "HP", abilities: "Abilities", saves: "Saving Throws",
  skills: "Skills", vulnerabilities: "Vulnerabilities", resistances: "Resistances", immunities: "Immunities",
  "condition-immunities": "Condition Immunities", gear: "Gear", languages: "Languages", cr: "CR",
  habitat: "Habitat", treasure: "Treasure", roll: "Roll", class: "Class", subclass: "Subclass",
  dt: "Damage Threshold", capacity: "Capacity",
});
const DND_LABEL_RE = /^([a-z][a-z-]{0,23}):(.*)$/s;
const DND_LINE = 100; // short fields share a line up to about this long
// 'Failure:', 'Trigger:', '1/Day Each:' lead-ins
const DND_COLON_RE = /^([A-Z0-9][A-Za-z0-9’'\/ -]{0,30}):(?=\s)/;
// small words allowed lowercase in a 'Fire Breath (Recharge 5–6).' style lead-in
const SMALL_WORDS = new Set(["a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to",
  "with", "per", "vs"]);

/** Bold a paragraph's 'Name (uses).' or 'Failure:' lead-in, as the stat blocks and rules print them. */
function dndLeadIn(line: string): string {
  if (/^(__|\*\*|```)/.test(line)) return line;
  if (DND_COLON_RE.test(line)) return line.replace(DND_COLON_RE, "**$1:**");
  const m = /^([A-Z0-9][^.]{0,60}?)\.(?= \S)/.exec(line);
  if (!m) return line;
  const ok = m[1]!.split(" ").every((w) => {
    const word = w.replace(/^[("'‘“]+/, "");
    return !/^[a-z]/.test(word) || SMALL_WORDS.has(word);
  });
  return ok ? `**${m[1]}.**${line.slice(m[0].length)}` : line;
}

function dndParagraphs(text: string): string {
  return paragraphs(text, false, true).split("\n").map(dndLeadIn).join("\n");
}

/** 'Cantrips: Acid Splash, ...; Level 1: Alarm, ...' -> one line per spell level. */
function spellList(value: string): string {
  return value
    .split("; ")
    .map((e) => {
      const m = /^(Cantrips|Level \d+): (.*)$/s.exec(e);
      return m ? `**${m[1]}** ${esc(m[2]!)}` : esc(e);
    })
    .join("\n");
}

/** Long labeled fields: the class features by level, class table columns, ability scores. */
function dndField(label: string, value: string): string {
  const name = DND_LABELS[label]!;
  if (label === "features")
    return `**${name}**\n` + value.split("; ").map((e) => {
      const m = /^(\d+): (.*)$/s.exec(e);
      return m ? `**${m[1]}** ${esc(m[2]!)}` : esc(e);
    }).join("\n");
  if (label === "scale")
    return `**${name}**\n` + value.split(" / ").map((col) => {
      const [title, , steps] = partition(col, ": ");
      return `• ${esc(title)}: ` + esc(steps.replace(/(^|, )(\d+) /g, "$1$2: "));
    }).join("\n");
  if (label === "abilities")
    return value.split(", ").map((a) => {
      const [abbr, , rest] = partition(a, " ");
      return `**${esc(abbr)}** ${esc(rest)}`;
    }).join(" · ");
  return `**${name}** ${esc(value)}`;
}

function renderDnd(rec: Rec): Rendered {
  const [game, stem, line] = rec;
  const parts = line.split("|");
  const r: Rendered = {
    game, stem,
    name: parts[0]!.replaceAll("¦", "|"),
    kind: parts[1] ?? "",
    source: "", remaster: false, xmlid: "", pages: [],
  };
  let header = r.kind ? `*${esc(capitalize(r.kind))}*` : "";
  const out: string[] = [];
  const short: string[] = [];
  const flush = () => {
    let cur = "";
    for (const s of short) {
      if (cur && cur.length + s.length + 3 > DND_LINE) {
        out.push(cur);
        cur = s;
      } else cur = cur ? `${cur} · ${s}` : s;
    }
    if (cur) out.push(cur);
    short.length = 0;
  };
  for (const p of parts.slice(2)) {
    const m = DND_LABEL_RE.exec(p);
    const label = m?.[1] ?? "";
    if (m && label === "book") r.source = m[2]!;
    else if (m && label === "tag") header = `*${esc(m[2]!)}*`; // 'Huge Dragon, Chaotic Evil' for monsters
    else if (m && label in DND_LABELS) {
      const value = label === "class" || label === "subclass" ? capitalize(m[2]!.replaceAll("-", " ")) : m[2]!;
      if (value.length <= 40 && !["features", "scale", "abilities"].includes(label))
        short.push(`**${DND_LABELS[label]}** ${esc(value)}`);
      else {
        flush();
        out.push(dndField(label, value));
      }
    } else {
      flush();
      if (r.kind === "table" && /^\d+(-\d+)?:/.test(p)) out.push(rollTable(p));
      else if (/^(Cantrips|Level \d+): /.test(p)) out.push(spellList(p));
      else out.push(dndParagraphs(p));
    }
  }
  flush();
  r.pages = paginate([...(header ? [header] : []), ...out]);
  return r;
}

/** Plain preview of every page, for the --preview CLI. */
export function toText(r: Rendered, sources?: Map<string, string>): string {
  return r.pages
    .map((p, i) => `=== ${r.name} [${r.game}/${r.stem}] ===\n${p}\n--- ${footer(r, sources, i)}`)
    .join("\n\n");
}
