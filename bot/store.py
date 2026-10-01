"""In-memory copy of the extracted data, shared by all bot commands.

Records are (game, file stem, line) tuples, the same shape pf.py uses. Lookups cover
both games; each record's game travels with it.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skill" / "pf2e-rules" / "scripts"))
import pf  # noqa: E402

GAMES = ("pf2e", "sf2e")
# Full-text search order: rules text and player-facing options before stat blocks,
# so e.g. a legacy name finds the Remaster Changes page before creatures that mention it.
SEARCH_FIRST = ("rules", "conditions", "actions", "traits", "spells", "feats", "class-features", "equipment")
SEP = "§"  # joins game, file stem and name in autocomplete values


def name_of(rec):
    return rec[2].split("|", 1)[0]


def kind_of(rec):
    parts = rec[2].split("|", 2)
    return parts[1] if len(parts) > 1 else ""


def encode(rec):
    """Autocomplete value that resolves back to exactly this record."""
    return f"{rec[0]}{SEP}{rec[1]}{SEP}{name_of(rec)}"


class Store:
    def __init__(self, data=None):
        self.data = Path(data or os.environ.get("PF_DATA") or pf.DATA)
        pf.DATA = self.data
        self.records = [r for g in GAMES for r in pf.load(g)]
        self.lore = {g: {name_of(r): r for r in pf.load(g, "creature-lore")} for g in GAMES}
        order = {stem: i for i, stem in enumerate(SEARCH_FIRST)}
        self.search_order = sorted(self.records, key=lambda r: order.get(r[1], len(order)))
        self.names = [(name_of(r).lower(), r) for r in self.records]
        self.sources = {}
        src = self.data / "sources.txt"
        if src.exists():
            for line in src.read_text().splitlines():
                code, _, title = line.partition("|")
                self.sources[code] = title
        ver = self.data / "VERSION"
        self.version = {}
        if ver.exists():
            for line in ver.read_text().splitlines():
                tag = line.split()[0] if line.strip() else ""
                for g in GAMES:
                    if tag.startswith(g + "-"):
                        self.version[g] = tag

    def find(self, query):
        """Records for a query: an encoded autocomplete pick, else pf.rank() name matching."""
        parts = query.split(SEP)
        if len(parts) == 3:
            game, stem, name = parts
            hits = [r for r in self.records if r[0] == game and r[1] == stem and name_of(r) == name]
            if hits:
                return hits
            query = name
        return pf.rank(self.records, query.strip())

    def search(self, text, limit=25):
        return pf.grep(self.search_order, re.escape(text.strip()), limit)

    def suggest(self, current, limit=25):
        """Autocomplete candidates: prefix matches first, then substring matches."""
        q = current.strip().lower()
        if not q:
            return []
        prefix, sub = [], []
        for n, r in self.names:
            if n.startswith(q):
                prefix.append(r)
            elif q in n:
                sub.append(r)
        prefix.sort(key=lambda r: (len(name_of(r)), name_of(r)))
        return (prefix + sub)[:limit]

    def lore_for(self, rec):
        if rec[1] != "creatures":
            return None
        return self.lore[rec[0]].get(name_of(rec))
