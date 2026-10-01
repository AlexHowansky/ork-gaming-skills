// Tests for the data store and rendering; same cases as bots/python/test_render.py.
// Needs extracted data (./extract.py).
import { beforeAll, describe, expect, test } from "bun:test";
import * as render from "../src/render";
import { encode, nameOf, SEP, Store, type Rec } from "../src/store";

let store: Store;
beforeAll(async () => {
  store = await Store.load();
});

function first(game: string, query: string): Rec {
  return store.find(query).find((r) => r[0] === game)!;
}

describe("limits", () => {
  function check(rec: Rec) {
    const r = render.render(rec);
    expect(r.pages.length).toBeGreaterThan(0);
    r.pages.forEach((p, i) => {
      expect(p.length).toBeLessThanOrEqual(4096);
      expect(p.length + render.footer(r, store.sources, i).length + r.name.length).toBeLessThanOrEqual(6000);
      expect(p.split("```").length % 2).toBe(1); // fences balanced
    });
    return r;
  }

  test("largest records", () => {
    for (const game of ["pf2e", "sf2e"]) {
      const biggest = store.records.filter((r) => r[0] === game).sort((a, b) => a[2].length - b[2].length).slice(-20);
      biggest.forEach(check);
    }
  });

  test("big creature paginates", () => {
    const r = check(first("pf2e", "Hyrune Loxenna"));
    expect(r.pages.length).toBeGreaterThan(1);
    expect(render.footer(r, store.sources, 0)).toContain("Page 1/");
  });

  test("paginate splits overlong line", () => {
    const pages = render.paginate(["word ".repeat(2000)]);
    expect(pages.length).toBeGreaterThan(1);
    for (const p of pages) expect(p.length).toBeLessThanOrEqual(render.PAGE);
  });
});

describe("formatting", () => {
  test("spell", () => {
    const r = render.render(first("pf2e", "Fireball"));
    const body = r.pages[0]!;
    expect(body).toContain("`CONCENTRATE` `FIRE` `MANIPULATE`");
    expect(body).toContain("**Cast** ◆◆");
    expect(body).toContain("**Heightened (+1)**");
    expect(r.source).toBe("PC1");
    expect(r.remaster).toBe(true);
    expect(render.footer(r, store.sources)).toContain("Pathfinder Player Core (PC1)");
  });

  test("weapon", () => {
    const body = render.render(first("pf2e", "Longsword")).pages[0]!;
    expect(body).toContain("**Damage** 1d8 S");
    expect(body).toContain("**Price** 1gp");
  });

  test("creature", () => {
    const body = render.render(first("pf2e", "Goblin Warrior")).pages[0]!;
    expect(body).toContain("`SMALL`");
    expect(body).toContain("**AC** 16 **Fort** +5 **Ref** +7 **Will** +3");
    expect(body).toContain("**Str** +0 **Dex** +3 **Con** +1 **Int** +0 **Wis** -1 **Cha** +1");
    expect(body).toContain("**Melee** Dogslicer +7 (agile, backstabber, finesse)");
    expect(body).toContain("• **Goblin Scuttle** ⟲");
  });

  test("rules table", () => {
    const r = render.render(first("pf2e", "GM Screen > Treat Wounds"));
    expect(r.source).toBe("");
    expect(r.pages[0]).toContain("```\nProficiency  DC");
  });

  test("headings", () => {
    expect(render.render(first("pf2e", "Classes > Wizard")).pages[0]).toContain("__**Roleplaying the Wizard**__");
  });

  test("glyphs", () => {
    expect(render.glyphs("Strike [2a] then [r] or [f]")).toBe("Strike ◆◆ then ⟲ or ◇");
    expect(render.glyphs("Activate A (manipulate)")).toBe("Activate ◆ (manipulate)");
  });

  test("escapes markdown", () => {
    expect(render.esc("a*b_c¦d")).toBe("a\\*b\\_c\\|d");
  });
});

describe("lookup", () => {
  test("encoded pick round trip", () => {
    const rec = first("pf2e", "Fireball");
    expect(encode(rec)).toBe(`pf2e${SEP}spells${SEP}Fireball`);
    expect(store.find(encode(rec))).toEqual([rec]);
  });

  test("encoded pick disambiguates files", () => {
    const hits = store.records.filter((r) => nameOf(r) === "Allegro");
    expect(hits.length).toBeGreaterThan(1);
    for (const rec of hits) expect(store.find(encode(rec))).toEqual([rec]);
  });

  test("encoded pick disambiguates games", () => {
    const hits = store.records.filter((r) => nameOf(r) === "GM Screen > DCs by Level");
    expect(new Set(hits.map((r) => r[0]))).toEqual(new Set(["pf2e", "sf2e"]));
    for (const rec of hits) expect(store.find(encode(rec))).toEqual([rec]);
  });

  test("suggest prefix first", () => {
    const names = store.suggest("fireb").map(nameOf);
    expect(names[0]).toBe("Fireball");
    expect(names.length).toBeLessThanOrEqual(25);
    expect(store.suggest("  ")).toEqual([]);
  });

  test("finds both games", () => {
    expect(new Set(store.find("Laser Pistol").map((r) => r[0]))).toEqual(new Set(["sf2e"]));
    expect(store.find("Fireball").map((r) => r[0])).toEqual(["pf2e", "sf2e"]); // PF2e listed first
    expect(new Set(store.find("GM Screen > DCs by Level").map((r) => r[0]))).toEqual(new Set(["pf2e", "sf2e"]));
    expect(store.suggest("laser pis").some((r) => r[0] === "sf2e")).toBe(true);
  });

  test("search fallback prefers rules", () => {
    expect(store.find("magic missile")).toEqual([]);
    expect(store.search("magic missile")[0]!.rec[1]).toBe("rules");
  });

  test("lore", () => {
    expect(store.loreFor(first("pf2e", "Goblin Warrior"))).toBeDefined();
    expect(store.loreFor(first("pf2e", "Fireball"))).toBeUndefined();
  });
});
