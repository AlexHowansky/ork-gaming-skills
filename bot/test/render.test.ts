// Tests for the data store and rendering.
// Needs extracted data (./extract_pf2e.py); the HERO, Cypher and D&D tests also need ./extract_hero.py,
// ./extract_cypher.py and ./extract_dnd5e.py and are skipped without them.
import { beforeAll, describe, expect, test } from "bun:test";
import * as render from "../src/render";
import { encode, nameOf, SEP, Store, type Rec } from "../src/store";

const hero = await Store.loadHero();
const cypher = await Store.loadCypher();
const dnd = await Store.loadDnd();

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

describe.skipIf(!hero.records.length)("hero", () => {
  const first = (game: string, query: string) => hero.find(query).find((r) => r[0] === game)!;

  test("6e first and id lookup", () => {
    expect(hero.find("Flight")[0]![0]).toBe("6e");
    expect(hero.find("ENERGYBLAST").map((r) => [r[0], nameOf(r)])).toEqual([["6e", "Blast"], ["5e", "Energy Blast"]]);
  });

  test("encoded pick disambiguates templates", () => {
    const hits = hero.records.filter((r) => r[0] === "6e" && nameOf(r) === "Flight");
    expect(hits.length).toBeGreaterThan(1);
    for (const rec of hits) expect(hero.find(encode(rec))).toEqual([rec]);
    expect(encode(hits[0]!)).toBe(`6e${SEP}powers${SEP}Flight${SEP}Main6E`);
  });

  test("power", () => {
    const r = render.render(first("6e", "Flight"));
    const body = r.pages[0]!;
    expect(body).toStartWith("*Power*\n**Type** movement · **Cost** +1 per 1, lvls 1+");
    expect(body).toContain("**Modifiers**\n• **Gliding** (-1): Flight purchased");
    expect(render.footer(r, hero.sources)).toBe("HERO System 6e · Main6E · FLIGHT");
  });

  test("nested options stay together", () => {
    const body = render.render(first("6e", "Area Of Effect")).pages[0]!;
    expect(body).toContain("• **Line** (+1/4 per 1) {Height (m) (+1/4 per 1, lvls 3+); Width (m)");
    expect(body).toContain("• **Nonselective** (-1/4) [excl SELECTIVETARGET]");
  });

  test("option label and plain items", () => {
    expect(render.render(first("6e", "Resource Points")).pages[0]).toContain("**Type**\n• **Equipment Points**");
    expect(render.render(first("6e", "Vehicle6E")).pages[0]).toContain("**Removes**\n• mainapp NCM");
  });

  test("largest records", () => {
    for (const rec of [...hero.records].sort((a, b) => a[2].length - b[2].length).slice(-20))
      for (const p of render.render(rec).pages) expect(p.length).toBeLessThanOrEqual(4096);
  });
});

describe.skipIf(!cypher.records.length)("cypher", () => {
  const first = (query: string, stem?: string) => cypher.find(query).find((r) => !stem || r[1] === stem)!;

  test("page name alone matches 'Journal > Page'", () => {
    expect(cypher.find("Warrior").map((r) => `${r[1]}:${nameOf(r)}`)).toEqual(["creatures:Warrior", "rules:Type > Warrior"]);
    expect(cypher.find("Bears a Halo of Fire").map(nameOf)).toEqual(["Focus > Bears a Halo of Fire"]);
  });

  test("encoded pick disambiguates genres and packs", () => {
    const seen = new Map<string, number>();
    for (const rec of cypher.records) seen.set(encode(rec), (seen.get(encode(rec)) ?? 0) + 1);
    const dupes = cypher.records.filter((r) => seen.get(encode(r))! > 1);
    for (const rec of cypher.records.filter((r) => !dupes.includes(r)).slice(0, 500)) expect(cypher.find(encode(rec))).toEqual([rec]);
    const trolls = cypher.records.filter((r) => nameOf(r) === "Troll");
    expect(new Set(trolls.map(encode)).size).toBe(trolls.length);
  });

  test("labels share a line, text keeps lead-ins", () => {
    const r = render.render(first("Ghost", "creatures"));
    expect(r.pages[0]).toStartWith("*Creature*\n**Level** 4 (target 12) · **Health** 12 · **Damage** 5\n");
    expect(r.pages[0]).toContain("\n**Motive:** Unpredictable");
    expect(render.footer(r)).toBe("Cypher System");
  });

  test("ability, genre and book footers", () => {
    expect(render.render(first("Temporal Dislocation")).pages[0]).toStartWith("*Ability*\n**Cost** 7 Intellect\nYou disappear");
    expect(render.footer(render.render(first("Blaster rifle, heavy")))).toBe("Cypher System · sci-fi");
    const atk = render.render(first("Rules of the Game > Action: Attack"));
    expect(render.footer(atk, undefined, 0)).toStartWith("Cypher System · Cypher System Rulebook > Part 2: Rules · Page 1/");
    expect(atk.pages.join("\n")).not.toContain("**Special**");
  });

  test("roll table", () => {
    const body = render.render(first("Over the Counter Medicine")).pages[0]!;
    expect(body).toContain("**Roll** 1d10\nProvides an asset");
    expect(body).toContain("\n**8-9** Pain and discomfort relief");
  });

  test("largest records", () => {
    for (const rec of [...cypher.records].sort((a, b) => a[2].length - b[2].length).slice(-20))
      for (const p of render.render(rec).pages) {
        expect(p.length).toBeLessThanOrEqual(4096);
        expect(p.split("```").length % 2).toBe(1);
      }
  });
});

describe.skipIf(!dnd.records.length)("dnd", () => {
  const first = (query: string, game = "dnd2024", stem?: string) =>
    dnd.find(query).find((r) => r[0] === game && (!stem || r[1] === stem))!;

  test("2024 before 2014; page name alone matches 'Journal > Page'", () => {
    expect(dnd.find("Grappled").map((r) => `${r[0]}:${nameOf(r)}`)).toEqual([
      "dnd2024:Rules Glossary > Grappled",
      "dnd2014:Appendix A: Conditions > Grappled",
    ]);
    expect(dnd.find("Fireball").map((r) => r[0])).toEqual(["dnd2024", "dnd2014"]);
  });

  test("encoded pick finds the record again", () => {
    for (const rec of dnd.records.slice(0, 500)) expect(dnd.find(encode(rec))).toContain(rec);
  });

  test("monster stat block", () => {
    const r = render.render(first("Adult Red Dragon"));
    const page = r.pages[0]!;
    expect(page).toStartWith("*Huge Dragon, Chaotic Evil*\n**AC** 19 · **Initiative** +12 (22) · **HP** 256 (19d12 + 133)\n");
    expect(page).toContain("\n**Str** 27 (+8) · **Dex** 10 (+0) · ");
    expect(page).toContain("\n__**Actions**__\n**Multiattack.** ");
    expect(page).toContain("\n**Fire Breath (Recharge 5–6).** Dexterity Saving Throw: DC 21");
    expect(page).toContain("\n**Failure:** 59 (17d6) Fire damage.");
    expect(page).not.toContain(" / ");
    expect(render.footer(r)).toBe("D&D 5e (2024)");
  });

  test("class features by level and table columns", () => {
    const page = render.render(first("Fighter", "dnd2024", "classes")).pages[0]!;
    expect(page).toContain("**Features**\n**1** Fighting Style, Second Wind, Weapon Mastery\n**2** Action Surge");
    expect(page).toContain("• Second Wind: 1: 2, 4: 3, 10: 4");
    expect(page).toContain("\n**Primary Ability** Strength or Dexterity\n**Hit Point Die** D10 per Fighter level");
  });

  test("tables: grid when the cells line up, else one row per line", () => {
    const barb = render.render(first("Barbarian", "dnd2014", "classes")).pages.join("\n");
    expect(barb).toMatch(/```\nLevel +Proficiency Bonus +Features +Rages +Rage Damage\n1st +\+2 +Rage, Unarmored Defense +2 +\+2\n/);
    const actions = render.render(first("Actions > Overview"));
    expect(actions.pages[0]).toContain("\n**Attack** Attack with a weapon or an Unarmed Strike.\n**Dash** ");
    expect(render.footer(actions)).toBe("D&D 5e (2024) · Chapter 1");
  });

  test("spell, spell list and roll table", () => {
    expect(render.render(first("Fireball")).pages[0]).toStartWith(
      "*Spell*\n**Level** 3 · **School** Evocation · **Casting Time** Action · **Range** 150 feet\n",
    );
    const list = render.render(first("Wizard Spell List")).pages[0]!;
    expect(list).toContain("\n**Cantrips** Acid Splash, ");
    expect(list).toContain("\n**Level 9** Astral Projection, ");
    expect(render.render(first("Reincarnate", "dnd2014", "tables")).pages[0]).toContain("\n**1-4** Dragonborn\n");
  });

  test("lore for monsters only", () => {
    expect(dnd.loreFor(first("Adult Red Dragon"))).toBeDefined();
    expect(dnd.loreFor(first("Fireball"))).toBeUndefined();
    expect(dnd.find("Adult Red Dragon").every((r) => r[1] === "monsters")).toBe(true); // lore isn't searched
  });

  test("largest records", () => {
    for (const rec of [...dnd.records].sort((a, b) => a[2].length - b[2].length).slice(-20))
      for (const p of render.render(rec).pages) {
        expect(p.length).toBeLessThanOrEqual(4096);
        expect(p.split("```").length % 2).toBe(1);
      }
  });
});
