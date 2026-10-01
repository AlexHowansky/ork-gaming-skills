#!/usr/bin/env python3
"""Look up PF2e/SF2e records.

  pf.py NAME [NAME...]        records whose name matches (exact, then prefix, then substring)
  pf.py -s REGEX              list names of records whose text matches (full-text search)
options: -g pf2e|sf2e  -f FILE (e.g. creatures, spells)  -n MAX (default 5 records / 60 search hits)  -r (raw one-line output)
"""
import argparse
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


OPT_IN = {"creature-lore"}  # only searched when named with -f


def files(game, fname):
    for gd in sorted(DATA.iterdir()):
        if not gd.is_dir() or (game and gd.name != game):
            continue
        for f in sorted(gd.glob("*.txt")):
            if f.stem == "index" or (fname and f.stem != fname) or (not fname and f.stem in OPT_IN):
                continue
            yield gd.name, f


def records(game=None, fname=None):
    """Yield (game, file stem, line) for every record, streaming from disk."""
    for g, f in files(game, fname):
        with f.open() as fh:
            for line in fh:
                yield g, f.stem, line.rstrip("\n")


def load(game=None, fname=None):
    """All records as a list, for callers that keep the data in memory."""
    return list(records(game, fname))


def rank(recs, name):
    """Records whose name matches: exact if any, else prefix, else substring (case-insensitive)."""
    q = name.lower()
    tiers = ([], [], [])
    for r in recs:
        n = r[2].split("|", 1)[0].lower()
        if n == q:
            tiers[0].append(r)
        elif n.startswith(q):
            tiers[1].append(r)
        elif q in n:
            tiers[2].append(r)
    return next((t for t in tiers if t), [])


def grep(recs, rx, limit):
    """Up to `limit` (record, match) pairs whose text matches regex `rx` (case-insensitive)."""
    pat = re.compile(rx, re.I)
    out = []
    for r in recs:
        m = pat.search(r[2])
        if m:
            out.append((r, m))
            if len(out) >= limit:
                break
    return out


def show(game, stem, line, raw):
    if raw:
        print(f"[{game}/{stem}] {line}")
        return
    parts = line.split("|")
    print(f"== {parts[0]}  [{game}/{stem}] {' '.join(parts[1:3])}")
    for p in parts[3:]:
        print("  " + p.replace(" / ", "\n    "))


def lookup(names, a):
    for name in names:
        hits = rank(records(a.g, a.f), name)
        if not hits:
            print(f"no match: {name}")
        for h in hits[: a.n or 5]:
            show(*h, a.r)
        if len(hits) > (a.n or 5):
            print(f"... {len(hits) - (a.n or 5)} more: " + "; ".join(h[2].split("|", 1)[0] for h in hits[(a.n or 5):][:40]))


def search(rx, a):
    hits = grep(records(a.g, a.f), rx, a.n or 60)
    for (game, stem, line), m in hits:
        parts = line.split("|", 3)
        s = max(0, m.start() - 60)
        print(f"[{game}/{stem}] {parts[0]}|{parts[1] if len(parts) > 1 else ''} …{line[s:m.end() + 60].strip()}…")
    if len(hits) >= (a.n or 60):
        print("... (limit reached; narrow with -f/-g or a tighter regex)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("terms", nargs="+")
    ap.add_argument("-s", action="store_true", help="full-text regex search")
    ap.add_argument("-g", choices=["pf2e", "sf2e"])
    ap.add_argument("-f")
    ap.add_argument("-n", type=int)
    ap.add_argument("-r", action="store_true")
    a = ap.parse_args()
    if a.s:
        search(" ".join(a.terms), a)
    else:
        lookup(a.terms, a)


if __name__ == "__main__":
    main()
