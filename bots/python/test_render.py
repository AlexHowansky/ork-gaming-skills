"""Tests for the bot's data store and rendering. Needs extracted data (./extract_pf2e.py).

  bots/python/.venv/bin/python -m unittest discover bots/python
"""
import unittest

import render
from store import SEP, Store, encode, name_of

STORE = None


def setUpModule():
    global STORE
    STORE = Store()


def first(game, query):
    return next(r for r in STORE.find(query) if r[0] == game)


class Limits(unittest.TestCase):
    def check(self, rec):
        r = render.render(rec)
        self.assertTrue(r.pages)
        for i, p in enumerate(r.pages):
            self.assertLessEqual(len(p), 4096, f"{r.name} page {i}")
            footer = render.footer(r, STORE, i)
            self.assertLessEqual(len(p) + len(footer) + len(r.name), 6000)
            self.assertEqual(p.count("```") % 2, 0, f"{r.name} page {i} has an unclosed code block")
        return r

    def test_largest_records(self):
        for game in ("pf2e", "sf2e"):
            biggest = sorted((r for r in STORE.records if r[0] == game), key=lambda r: len(r[2]))[-20:]
            for rec in biggest:
                self.check(rec)

    def test_big_creature_paginates(self):
        r = self.check(first("pf2e", "Hyrune Loxenna"))
        self.assertGreater(len(r.pages), 1)
        self.assertIn("Page 1/", render.footer(r, STORE, 0))

    def test_paginate_splits_overlong_line(self):
        pages = render.paginate(["word " * 2000])
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(p) <= render.PAGE for p in pages))


class Formatting(unittest.TestCase):
    def test_spell(self):
        r = render.render(first("pf2e", "Fireball"))
        body = r.pages[0]
        self.assertIn("`CONCENTRATE` `FIRE` `MANIPULATE`", body)
        self.assertIn("**Cast** ◆◆", body)
        self.assertIn("**Heightened (+1)**", body)
        self.assertEqual(r.source, "PC1")
        self.assertTrue(r.remaster)
        self.assertIn("Pathfinder Player Core (PC1)", render.footer(r, STORE))

    def test_weapon(self):
        body = render.render(first("pf2e", "Longsword")).pages[0]
        self.assertIn("**Damage** 1d8 S", body)
        self.assertIn("**Price** 1gp", body)

    def test_creature(self):
        body = render.render(first("pf2e", "Goblin Warrior")).pages[0]
        self.assertIn("`SMALL`", body)
        self.assertIn("**AC** 16 **Fort** +5 **Ref** +7 **Will** +3", body)
        self.assertIn("**Str** +0 **Dex** +3 **Con** +1 **Int** +0 **Wis** -1 **Cha** +1", body)
        self.assertIn("**Melee** Dogslicer +7 (agile, backstabber, finesse)", body)
        self.assertIn("• **Goblin Scuttle** ⟲", body)

    def test_rules_table(self):
        r = render.render(first("pf2e", "GM Screen > Treat Wounds"))
        self.assertEqual(r.source, "")
        self.assertIn("```\nProficiency  DC", r.pages[0])

    def test_headings(self):
        body = render.render(first("pf2e", "Classes > Wizard")).pages[0]
        self.assertIn("__**Roleplaying the Wizard**__", body)

    def test_glyphs(self):
        self.assertEqual(render.glyphs("Strike [2a] then [r] or [f]"), "Strike ◆◆ then ⟲ or ◇")
        self.assertEqual(render.glyphs("Activate A (manipulate)"), "Activate ◆ (manipulate)")

    def test_escapes_markdown(self):
        self.assertEqual(render.esc("a*b_c¦d"), r"a\*b\_c\|d")


class Lookup(unittest.TestCase):
    def test_encoded_pick_round_trip(self):
        rec = first("pf2e", "Fireball")
        value = encode(rec)
        self.assertEqual(value, f"pf2e{SEP}spells{SEP}Fireball")
        self.assertEqual(STORE.find(value), [rec])

    def test_encoded_pick_disambiguates_files(self):
        hits = [r for r in STORE.records if name_of(r) == "Allegro"]
        self.assertGreater(len(hits), 1)
        for rec in hits:
            self.assertEqual(STORE.find(encode(rec)), [rec])

    def test_encoded_pick_disambiguates_games(self):
        hits = [r for r in STORE.records if name_of(r) == "GM Screen > DCs by Level"]
        self.assertEqual({r[0] for r in hits}, {"pf2e", "sf2e"})
        for rec in hits:
            self.assertEqual(STORE.find(encode(rec)), [rec])

    def test_suggest_prefix_first(self):
        names = [name_of(r) for r in STORE.suggest("fireb")]
        self.assertEqual(names[0], "Fireball")
        self.assertLessEqual(len(names), 25)
        self.assertEqual(STORE.suggest("  "), [])

    def test_finds_both_games(self):
        self.assertEqual({r[0] for r in STORE.find("Laser Pistol")}, {"sf2e"})
        self.assertEqual([r[0] for r in STORE.find("Fireball")], ["pf2e", "sf2e"])  # PF2e listed first
        self.assertEqual({r[0] for r in STORE.find("GM Screen > DCs by Level")}, {"pf2e", "sf2e"})
        self.assertIn("sf2e", {r[0] for r in STORE.suggest("laser pis")})

    def test_search_fallback_prefers_rules(self):
        self.assertFalse(STORE.find("magic missile"))
        (rec, _), *_ = STORE.search("magic missile")
        self.assertEqual(rec[1], "rules")

    def test_lore(self):
        self.assertIsNotNone(STORE.lore_for(first("pf2e", "Goblin Warrior")))
        self.assertIsNone(STORE.lore_for(first("pf2e", "Fireball")))


if __name__ == "__main__":
    unittest.main()
