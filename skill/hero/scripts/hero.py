#!/usr/bin/env python3
"""Look up HERO System (5e/6e) records from HERO Designer's rules data.

  hero.py NAME [NAME...]      records whose name matches (exact name or id, then prefix, then substring)
  hero.py -s REGEX            list names of records whose text matches (full-text search)
options: -g 5e|6e  -f FILE (e.g. powers, modifiers)  -t SYSTEM (e.g. Main6E, Vehicle6E)
         -n MAX (default 5 records / 60 search hits)  -r (raw one-line output)
"""
import argparse
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def files(game, fname):
    for gd in sorted(DATA.iterdir(), reverse=True):  # 6e before 5e
        if not gd.is_dir() or (game and gd.name != game):
            continue
        for f in sorted(gd.glob("*.txt")):
            if f.stem == "index" or (fname and f.stem != fname):
                continue
            yield gd.name, f


def records(game=None, fname=None, system=None):
    """Yield (edition, file stem, line) for every record, streaming from disk."""
    for g, f in files(game, fname):
        with f.open() as fh:
            for line in fh:
                if system and line.split("|", 3)[2:3] != [system]:
                    continue
                yield g, f.stem, line.rstrip("\n")


def rank(recs, name):
    """Records whose name matches: exact name or id if any, else prefix, else substring (case-insensitive)."""
    q = name.lower()
    tiers = ([], [], [])
    for r in recs:
        parts = r[2].split("|", 4)
        n = parts[0].lower()
        if n == q or (len(parts) > 3 and parts[3].lower() == "id:" + q):
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
        hits = rank(records(a.g, a.f, a.t), name)
        if not hits:
            print(f"no match: {name}")
        for h in hits[: a.n or 5]:
            show(*h, a.r)
        if len(hits) > (a.n or 5):
            print(f"... {len(hits) - (a.n or 5)} more: " + "; ".join(
                "%s [%s %s]" % (h[2].split("|", 1)[0], h[0], h[2].split("|", 3)[2]) for h in hits[(a.n or 5):][:40]))


def search(rx, a):
    hits = grep(records(a.g, a.f, a.t), rx, a.n or 60)
    for (game, stem, line), m in hits:
        parts = line.split("|", 3)
        s = max(0, m.start() - 60)
        print(f"[{game}/{stem}] {'|'.join(parts[:3])} …{line[s:m.end() + 60].strip()}…")
    if len(hits) >= (a.n or 60):
        print("... (limit reached; narrow with -f/-g/-t or a tighter regex)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("terms", nargs="+")
    ap.add_argument("-s", action="store_true", help="full-text regex search")
    ap.add_argument("-g", choices=["5e", "6e"])
    ap.add_argument("-f")
    ap.add_argument("-t")
    ap.add_argument("-n", type=int)
    ap.add_argument("-r", action="store_true")
    a = ap.parse_args()
    if a.s:
        search(" ".join(a.terms), a)
    else:
        lookup(a.terms, a)


if __name__ == "__main__":
    main()
