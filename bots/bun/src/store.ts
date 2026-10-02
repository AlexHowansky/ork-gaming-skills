/**
 * In-memory copy of the extracted data, shared by all bot commands.
 *
 * A port of skill/pf2e/scripts/pf.py and skill/hero/scripts/hero.py (load/rank/grep) and
 * bots/python/store.py. Records are [game, file stem, line] tuples. Store.load() holds PF2e
 * and SF2e for /sf, and its only("pf", ["pf2e"]) the PF2e part for /pf; Store.loadHero() holds
 * HERO System 6e and 5e for /hero. Lookups cover every game in the store; each record's game
 * travels with it.
 */
import { readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

export type Rec = readonly [game: string, stem: string, line: string];
export type Hit = { rec: Rec; start: number; end: number };

export const GAMES = ["pf2e", "sf2e"] as const;
export const HERO_GAMES = ["6e", "5e"] as const; // 6e first, like hero.py
const OPT_IN = new Set(["creature-lore"]); // only loaded when asked for by name
// Full-text search order: rules text and player-facing options before stat blocks,
// so e.g. a legacy name finds the Remaster Changes page before creatures that mention it.
const SEARCH_FIRST = ["rules", "conditions", "actions", "traits", "spells", "feats", "class-features", "equipment"];
export const SEP = "§"; // joins game, file stem and name in autocomplete values

export const DEFAULT_DATA = resolve(import.meta.dir, "../../../skill/pf2e/data");
export const DEFAULT_HERO_DATA = resolve(import.meta.dir, "../../../skill/hero/data");

export function nameOf(rec: Rec): string {
  const i = rec[2].indexOf("|");
  return i < 0 ? rec[2] : rec[2].slice(0, i);
}

export function kindOf(rec: Rec): string {
  const parts = rec[2].split("|", 2);
  return parts.length > 1 ? parts[1]! : "";
}

function isHero(rec: Rec): boolean {
  return (HERO_GAMES as readonly string[]).includes(rec[0]);
}

/** HERO Designer template of a HERO record ('Main6E', 'Vehicle6E', ...); '' for PF2e/SF2e. */
export function systemOf(rec: Rec): string {
  if (!isHero(rec)) return "";
  return rec[2].split("|", 3)[2] ?? "";
}

/**
 * Autocomplete value that resolves back to exactly this record.
 * HERO records repeat names across templates within a file, so theirs add the template.
 */
export function encode(rec: Rec): string {
  const value = `${rec[0]}${SEP}${rec[1]}${SEP}${nameOf(rec)}`;
  return isHero(rec) ? `${value}${SEP}${systemOf(rec)}` : value;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
}

/** Lines of a file the way Python iterates them: split on \n, no trailing empty line. */
function lines(text: string): string[] {
  const out = text.split("\n");
  if (out.length && out[out.length - 1] === "") out.pop();
  return out;
}

/** Records whose name matches: exact if any, else prefix, else substring (case-insensitive). */
export function rank(recs: readonly Rec[], name: string): Rec[] {
  const q = name.toLowerCase();
  const tiers: Rec[][] = [[], [], []];
  for (const r of recs) {
    const n = nameOf(r).toLowerCase();
    if (n === q) tiers[0]!.push(r);
    else if (n.startsWith(q)) tiers[1]!.push(r);
    else if (n.includes(q)) tiers[2]!.push(r);
  }
  return tiers.find((t) => t.length) ?? [];
}

/** Like rank(), but an exact HERO Designer id (e.g. ENERGYBLAST) also counts as an exact match. */
export function rankHero(recs: readonly Rec[], name: string): Rec[] {
  const q = name.toLowerCase();
  const tiers: Rec[][] = [[], [], []];
  for (const r of recs) {
    const parts = r[2].split("|", 4);
    const n = parts[0]!.toLowerCase();
    if (n === q || (parts.length > 3 && parts[3]!.toLowerCase() === "id:" + q)) tiers[0]!.push(r);
    else if (n.startsWith(q)) tiers[1]!.push(r);
    else if (n.includes(q)) tiers[2]!.push(r);
  }
  return tiers.find((t) => t.length) ?? [];
}

/** Up to `limit` records whose text matches `pattern` (case-insensitive). */
export function grep(recs: readonly Rec[], pattern: string, limit: number): Hit[] {
  const pat = new RegExp(pattern, "i");
  const out: Hit[] = [];
  for (const rec of recs) {
    const m = pat.exec(rec[2]);
    if (m) {
      out.push({ rec, start: m.index, end: m.index + m[0].length });
      if (out.length >= limit) break;
    }
  }
  return out;
}

/** Parses a HERO_EDITIONS value like "5e,6e"; unset or blank means every edition. */
export function heroEditions(value?: string): string[] {
  const picked = (value ?? "").split(",").map((e) => e.trim().toLowerCase()).filter(Boolean);
  if (!picked.length) return [...HERO_GAMES];
  const bad = picked.filter((e) => !(HERO_GAMES as readonly string[]).includes(e));
  if (bad.length) throw new Error(`HERO_EDITIONS: unknown edition ${bad.join(", ")} (expected ${HERO_GAMES.join(", ")})`);
  return HERO_GAMES.filter((g) => picked.includes(g));
}

export class Store {
  records: Rec[] = [];
  lore = new Map<string, Map<string, Rec>>();
  searchOrder: Rec[] = [];
  names: [string, Rec][] = [];
  sources = new Map<string, string>();
  version = new Map<string, string>();

  private constructor(
    readonly data: string,
    readonly command: "pf" | "sf" | "hero", // slash command it answers; also its component custom id prefix
  ) {}

  /** PF2e and SF2e records for /sf. */
  static async load(data?: string): Promise<Store> {
    const s = new Store(data || process.env.PF_DATA || DEFAULT_DATA, "sf");
    for (const g of GAMES) s.records.push(...(await s.read(g)));
    for (const g of GAMES) s.lore.set(g, new Map((await s.read(g, "creature-lore")).map((r) => [nameOf(r), r])));
    s.index();
    const src = Bun.file(join(s.data, "sources.txt"));
    if (await src.exists()) {
      for (const line of lines(await src.text())) {
        const i = line.indexOf("|");
        s.sources.set(i < 0 ? line : line.slice(0, i), i < 0 ? "" : line.slice(i + 1));
      }
    }
    const ver = Bun.file(join(s.data, "VERSION"));
    if (await ver.exists()) {
      for (const line of lines(await ver.text())) {
        const tag = line.trim().split(/\s+/)[0] ?? "";
        for (const g of GAMES) if (tag.startsWith(g + "-")) s.version.set(g, tag);
      }
    }
    return s;
  }

  /**
   * HERO System records for /hero: the editions in HERO_EDITIONS (comma-separated, e.g. "6e"),
   * else 6e and 5e. Empty if the data hasn't been extracted.
   */
  static async loadHero(data?: string, editions = heroEditions(process.env.HERO_EDITIONS)): Promise<Store> {
    const s = new Store(data || process.env.HERO_DATA || DEFAULT_HERO_DATA, "hero");
    for (const g of HERO_GAMES) if (editions.includes(g)) s.records.push(...(await s.read(g)));
    s.index();
    const ver = Bun.file(join(s.data, "VERSION"));
    if (await ver.exists()) s.version.set("hero", (await ver.text()).split(",", 1)[0]!.trim());
    return s;
  }

  /** A store for `command` holding only this one's records from `games`, sharing the record data. */
  only(command: Store["command"], games: readonly string[]): Store {
    const s = new Store(this.data, command);
    s.records = this.records.filter((r) => games.includes(r[0]));
    for (const g of games) if (this.lore.has(g)) s.lore.set(g, this.lore.get(g)!);
    s.sources = this.sources;
    for (const [g, v] of this.version) if (games.includes(g)) s.version.set(g, v);
    s.index();
    return s;
  }

  private index() {
    const order = new Map(SEARCH_FIRST.map((stem, i) => [stem, i]));
    const pos = (r: Rec) => order.get(r[1]) ?? order.size;
    this.searchOrder = [...this.records].sort((a, b) => pos(a) - pos(b));
    this.names = this.records.map((r) => [nameOf(r).toLowerCase(), r]);
  }

  /** Records from data/<game>/*.txt in file-name order, like pf.files(). */
  private async read(game: string, fname?: string): Promise<Rec[]> {
    const dir = join(this.data, game);
    let entries: string[];
    try {
      if (!statSync(dir).isDirectory()) return [];
      entries = readdirSync(dir).filter((f) => f.endsWith(".txt")).sort();
    } catch {
      return [];
    }
    const out: Rec[] = [];
    for (const f of entries) {
      const stem = f.slice(0, -4);
      if (stem === "index" || (fname && stem !== fname) || (!fname && OPT_IN.has(stem))) continue;
      for (const line of lines(await Bun.file(join(dir, f)).text())) out.push([game, stem, line]);
    }
    return out;
  }

  /** Records for a query: an encoded autocomplete pick, else rank() name matching. */
  find(query: string): Rec[] {
    const parts = query.split(SEP);
    if (parts.length === 3 || parts.length === 4) {
      const [game, stem, name, system] = parts;
      const hits = this.records.filter(
        (r) => r[0] === game && r[1] === stem && nameOf(r) === name && (system === undefined || systemOf(r) === system),
      );
      if (hits.length) return hits;
      query = name!;
    }
    return (this.command === "hero" ? rankHero : rank)(this.records, query.trim());
  }

  search(text: string, limit = 25): Hit[] {
    return grep(this.searchOrder, escapeRegExp(text.trim()), limit);
  }

  /** Autocomplete candidates: prefix matches first, then substring matches. */
  suggest(current: string, limit = 25): Rec[] {
    const q = current.trim().toLowerCase();
    if (!q) return [];
    const prefix: Rec[] = [];
    const sub: Rec[] = [];
    for (const [n, r] of this.names) {
      if (n.startsWith(q)) prefix.push(r);
      else if (n.includes(q)) sub.push(r);
    }
    prefix.sort((a, b) => {
      const x = nameOf(a), y = nameOf(b);
      return x.length - y.length || (x < y ? -1 : x > y ? 1 : 0);
    });
    return [...prefix, ...sub].slice(0, limit);
  }

  loreFor(rec: Rec): Rec | undefined {
    if (rec[1] !== "creatures") return undefined;
    return this.lore.get(rec[0])?.get(nameOf(rec));
  }
}
