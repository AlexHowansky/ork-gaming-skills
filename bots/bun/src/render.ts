/**
 * Turn a compact record line into Discord markdown pages. A port of bots/python/render.py;
 * the two must produce the same text.
 *
 * Record format (see skill/pf2e/SKILL.md):
 *   Name|kind level|SRC [R]|label:value|...|description
 */
import type { Rec } from "./store";

/** Lookup table without Object.prototype keys, so e.g. a "constructor" trait isn't found. */
function dict<T>(o: Record<string, T>): Record<string, T> {
  return Object.assign(Object.create(null), o);
}

export const PAGE = 4000; // embed description limit is 4096
export const COLORS: Record<string, number> = dict({ pf2e: 0x5d0000, sf2e: 0x1f6fb2 });
export const GAME_NAMES: Record<string, string> = dict({ pf2e: "Pathfinder 2e", sf2e: "Starfinder 2e" });
export const GAME_TAGS: Record<string, string> = dict({ pf2e: "PF2e", sf2e: "SF2e" });

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

function isTable(par: string): boolean {
  const rows = par.split("; ");
  if (rows.length < 3) return false;
  return rows.slice(0, 3).every((r) => r.includes(",") && r.length < 60 && !r.includes(". "));
}

function table(par: string): string {
  const rows = par.split("; ").map((r) => r.split(","));
  const cells = rows.filter((r) => r.length > 1);
  const width = Math.max(...cells.map((r) => r.length));
  const widths = Array.from({ length: width }, (_, i) =>
    Math.max(0, ...cells.filter((r) => i < r.length).map((r) => r[i]!.length)),
  );
  const out = rows.map((r) =>
    r.length === 1 ? r[0]! : r.map((c, i) => c.padEnd(widths[i]!)).join("  ").trimEnd(),
  );
  const body = out.join("\n").replaceAll("`", "'").replaceAll("¦", "|");
  return "```\n" + body + "\n```";
}

function paragraph(par: string): string {
  par = par.trim();
  if (!par) return "";
  const m = /^\[([^\]]+)\]$/.exec(par);
  if (m) return `__**${esc(m[1]!)}**__`;
  if (isTable(par)) return table(par);
  let text = glyphs(esc(par));
  const k = KEYWORD_RE.exec(text);
  if (k) text = `**${k[0].replace(/:+$/, "")}**` + text.slice(k[0].length);
  return text;
}

function paragraphs(text: string): string {
  text = text.replace(/\s*\/\[([^\]]+)\]\/\s*/g, " / [$1] / ");
  return text
    .split(" / ")
    .map(paragraph)
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
    source: "", remaster: false, pages: [],
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
  if (r.pages.length > 1) bits.push(`Page ${page + 1}/${r.pages.length}`);
  return bits.join(" · ");
}

/** Plain preview of every page, for the --preview CLI. */
export function toText(r: Rendered, sources?: Map<string, string>): string {
  return r.pages
    .map((p, i) => `=== ${r.name} [${r.game}/${r.stem}] ===\n${p}\n--- ${footer(r, sources, i)}`)
    .join("\n\n");
}
