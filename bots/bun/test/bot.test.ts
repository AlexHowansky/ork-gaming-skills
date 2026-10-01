// Drives the interaction handlers with stand-in interaction objects, so component wiring
// (custom ids, paging, picks, lore, share, expiry) is checked without connecting to Discord.
import { beforeAll, expect, test } from "bun:test";
import { MessageFlags } from "discord.js";
import { command, complete, component, lookup } from "../src/bot";
import { nameOf, Store } from "../src/store";

let store: Store;
let hero: Store;
beforeAll(async () => {
  store = await Store.load();
  hero = await Store.loadHero();
});

type Sent = { kind: "reply" | "update" | "respond"; payload: any };

/** Payload as Discord would receive it: builders serialized to plain JSON. */
function json(payload: any) {
  return JSON.parse(JSON.stringify(payload, (_, v) => (v && typeof v.toJSON === "function" ? v.toJSON() : v)));
}

function slash(query: string) {
  const sent: Sent[] = [];
  const i: any = {
    options: { getString: () => query },
    reply: async (p: any) => void sent.push({ kind: "reply", payload: json(p) }),
  };
  return { i, sent };
}

function click(customId: string, values?: string[]) {
  const sent: Sent[] = [];
  const i: any = {
    customId,
    values,
    reply: async (p: any) => void sent.push({ kind: "reply", payload: json(p) }),
    update: async (p: any) => void sent.push({ kind: "update", payload: json(p) }),
  };
  return { i, sent };
}

const ids = (payload: any): string[] => payload.components.flatMap((row: any) => row.components.map((c: any) => c.custom_id));
const button = (payload: any, action: string) =>
  payload.components.flatMap((row: any) => row.components).find((c: any) => c.custom_id?.startsWith(`pf:${action}:`));

test("command definitions", () => {
  for (const name of ["pf", "hero"] as const) {
    const def = command(name).toJSON();
    expect(def.name).toBe(name);
    expect(def.options?.[0]).toMatchObject({ name: "query", required: true, autocomplete: true });
  }
});

test("autocomplete returns at most 25 valid choices", async () => {
  let choices: any[] = [];
  await complete({ options: { getFocused: () => "fire" }, respond: async (c: any) => void (choices = c) } as any, store);
  expect(choices.length).toBe(25);
  for (const c of choices) {
    expect(c.name.length).toBeLessThanOrEqual(100);
    expect(c.value.length).toBeLessThanOrEqual(100);
  }
  expect(choices[0].name.toLowerCase()).toStartWith("fire");
});

test("lookup replies privately with dropdown and buttons; paging, lore and share work", async () => {
  const { i, sent } = slash("Adamantine Dragon (Adult)");
  await lookup(i, store);
  const msg = sent[0]!.payload;
  expect(msg.flags).toBe(MessageFlags.Ephemeral);
  expect(msg.embeds[0].title).toBe("Adamantine Dragon (Adult)");
  expect(msg.embeds[0].footer.text).toContain("Page 1/");
  expect(button(msg, "prev").disabled).toBe(true);
  expect(button(msg, "lore")).toBeDefined();
  const id = ids(msg)[0]!.split(":")[2];

  const next = click(`pf:next:${id}`);
  await component(next.i, store);
  expect(next.sent[0]!.kind).toBe("update");
  expect(next.sent[0]!.payload.embeds[0].footer.text).toContain("Page 2/");
  expect(button(next.sent[0]!.payload, "prev").disabled).toBe(false);

  const share = click(`pf:share:${id}`);
  await component(share.i, store);
  expect(share.sent[0]!.kind).toBe("reply");
  expect(share.sent[0]!.payload.flags).toBeUndefined(); // public
  expect(share.sent[0]!.payload.embeds[0].footer.text).toContain("Page 2/");

  const lore = click(`pf:lore:${id}`);
  await component(lore.i, store);
  expect(lore.sent[0]!.payload.flags).toBe(MessageFlags.Ephemeral);
  expect(lore.sent[0]!.payload.embeds[0].title).toBe("Adamantine Dragon (Adult)");
  expect(lore.sent[0]!.payload.embeds[0].description).not.toContain("**AC**"); // lore text, not the stat block
});

test("several matches get a dropdown; picking switches record", async () => {
  const { i, sent } = slash("Fireball");
  await lookup(i, store);
  const msg = sent[0]!.payload;
  const menu = msg.components[0].components[0];
  expect(menu.options.map((o: any) => o.description)).toEqual(["PF2e spell 3 (spells)", "SF2e spell 3 (spells)"]);
  const pick = click(menu.custom_id, ["1"]);
  await component(pick.i, store);
  expect(pick.sent[0]!.kind).toBe("update");
  expect(pick.sent[0]!.payload.embeds[0].footer.text).toStartWith("Starfinder 2e");
});

test("no name match falls back to text search", async () => {
  const { i, sent } = slash("magic missile");
  await lookup(i, store);
  const msg = sent[0]!.payload;
  expect(msg.embeds[0].title).toBe("No name matches “magic missile”");
  expect(msg.embeds[0].description).toContain("Remaster Changes \\> Spells");
  const menu = msg.components[0].components[0];
  expect(menu.placeholder).toBe("Open a result");
  const pick = click(menu.custom_id, ["0"]);
  await component(pick.i, store);
  const shown = pick.sent[0]!.payload;
  expect(shown.embeds[0].title).toBe("Remaster Changes > Spells");
  expect(shown.components[0].components[0].placeholder).toBe("Other text matches");
});

test("nothing found", async () => {
  const { i, sent } = slash("qqqqzzzz");
  await lookup(i, store);
  expect(sent[0]!.payload.content).toBe("No match for “qqqqzzzz”.");
});

test("expired or unknown state", async () => {
  const c = click("pf:next:deadbeef");
  await component(c.i, store);
  expect(c.sent[0]!.payload.content).toContain("expired");
});

test("dropdown labels fit Discord limits for long names", async () => {
  const long = store.records.reduce((a, b) => (nameOf(b).length > nameOf(a).length ? b : a));
  const { i, sent } = slash(nameOf(long));
  await lookup(i, store);
  expect(sent[0]!.payload.embeds[0].title.length).toBeLessThanOrEqual(256);
});

const hasHero = (await Store.loadHero()).records.length > 0; // HERO data is optional

test.skipIf(!hasHero)("/hero: template variants get a dropdown and custom ids carry the command", async () => {
  const { i, sent } = slash("Flight");
  await lookup(i, hero);
  const msg = sent[0]!.payload;
  expect(msg.embeds[0].footer.text).toBe("HERO System 6e · Main6E · FLIGHT");
  const menu = msg.components[0].components[0];
  expect(menu.custom_id).toStartWith("hero:pick:");
  expect(menu.options[1].description).toBe("6e power Base6E (powers)");
  const pick = click(menu.custom_id, ["2"]);
  await component(pick.i, hero);
  expect(pick.sent[0]!.payload.embeds[0].footer.text).toBe("HERO System 6e · Vehicle6E · FLIGHT");
  const share = msg.components[1].components.find((c: any) => c.custom_id?.startsWith("hero:share:"));
  expect(share).toBeDefined();
});

test.skipIf(!hasHero)("/hero: autocomplete values resolve to one template's record", async () => {
  let choices: any[] = [];
  await complete({ options: { getFocused: () => "flight" }, respond: async (c: any) => void (choices = c) } as any, hero);
  const vehicle = choices.find((c) => c.name === "Flight — 6e power Vehicle6E (powers)");
  expect(hero.find(vehicle.value).map((r) => r[2].split("|")[2])).toEqual(["Vehicle6E"]);
});

test.skipIf(!hasHero)("/hero: id lookup and expiry message", async () => {
  const { i, sent } = slash("ENERGYBLAST");
  await lookup(i, hero);
  expect(sent[0]!.payload.embeds[0].title).toBe("Blast");
  const c = click("hero:next:deadbeef");
  await component(c.i, hero);
  expect(c.sent[0]!.payload.content).toBe("This result expired — run /hero again.");
});

test("/hero data missing leaves an empty store", async () => {
  expect((await Store.loadHero("/nonexistent")).records).toEqual([]);
});
