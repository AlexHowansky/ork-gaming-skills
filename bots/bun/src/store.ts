/**
 * In-memory copy of the extracted data, shared by all bot commands.
 *
 * A port of skill/pf2e-rules/scripts/pf.py (load/rank/grep) and bots/python/store.py.
 * Records are [game, file stem, line] tuples. Lookups cover both games; each
 * record's game travels with it.
 */
import { readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

export type Rec = readonly [game: string, stem: string, line: string];
export type Hit = { rec: Rec; start: number; end: number };

export const GAMES = ["pf2e", "sf2e"] as const;
const OPT_IN = new Set(["creature-lore"]); // only loaded when asked for by name
// Full-text search order: rules text and player-facing options before stat blocks,
// so e.g. a legacy name finds the Remaster Changes page before creatures that mention it.
const SEARCH_FIRST = ["rules", "conditions", "actions", "traits", "spells", "feats", "class-features", "equipment"];
export const SEP = "§"; // joins game, file stem and name in autocomplete values

export const DEFAULT_DATA = resolve(import.meta.dir, "../../../skill/pf2e-rules/data");

export function nameOf(rec: Rec): string {
  const i = rec[2].indexOf("|");
  return i < 0 ? rec[2] : rec[2].slice(0, i);
}

export function kindOf(rec: Rec): string {
  const parts = rec[2].split("|", 2);
  return parts.length > 1 ? parts[1]! : "";
}

/** Autocomplete value that resolves back to exactly this record. */
export function encode(rec: Rec): string {
  return `${rec[0]}${SEP}${rec[1]}${SEP}${nameOf(rec)}`;
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

export class Store {
  records: Rec[] = [];
  lore = new Map<string, Map<string, Rec>>();
  searchOrder: Rec[] = [];
  names: [string, Rec][] = [];
  sources = new Map<string, string>();
  version = new Map<string, string>();

  private constructor(readonly data: string) {}

  static async load(data?: string): Promise<Store> {
    const s = new Store(data || process.env.PF_DATA || DEFAULT_DATA);
    for (const g of GAMES) s.records.push(...(await s.read(g)));
    for (const g of GAMES) s.lore.set(g, new Map((await s.read(g, "creature-lore")).map((r) => [nameOf(r), r])));
    const order = new Map(SEARCH_FIRST.map((stem, i) => [stem, i]));
    const pos = (r: Rec) => order.get(r[1]) ?? order.size;
    s.searchOrder = [...s.records].sort((a, b) => pos(a) - pos(b));
    s.names = s.records.map((r) => [nameOf(r).toLowerCase(), r]);
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
    if (parts.length === 3) {
      const [game, stem, name] = parts;
      const hits = this.records.filter((r) => r[0] === game && r[1] === stem && nameOf(r) === name);
      if (hits.length) return hits;
      query = name!;
    }
    return rank(this.records, query.trim());
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
