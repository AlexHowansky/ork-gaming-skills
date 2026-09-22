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


def show(game, f, line, raw):
    if raw:
        print(f"[{game}/{f.stem}] {line}")
        return
    parts = line.split("|")
    print(f"== {parts[0]}  [{game}/{f.stem}] {' '.join(parts[1:3])}")
    for p in parts[3:]:
        print("  " + p.replace(" / ", "\n    "))


def lookup(names, a):
    for name in names:
        q = name.lower()
        tiers = ([], [], [])
        for game, f in files(a.g, a.f):
            with f.open() as fh:
                for line in fh:
                    n = line.split("|", 1)[0].lower()
                    if n == q:
                        tiers[0].append((game, f, line.rstrip("\n")))
                    elif n.startswith(q):
                        tiers[1].append((game, f, line.rstrip("\n")))
                    elif q in n:
                        tiers[2].append((game, f, line.rstrip("\n")))
        hits = next((t for t in tiers if t), [])
        if not hits:
            print(f"no match: {name}")
        for h in hits[: a.n or 5]:
            show(*h, a.r)
        if len(hits) > (a.n or 5):
            print(f"... {len(hits) - (a.n or 5)} more: " + "; ".join(h[2].split("|", 1)[0] for h in hits[(a.n or 5):][:40]))


def search(rx, a):
    pat = re.compile(rx, re.I)
    n = 0
    for game, f in files(a.g, a.f):
        with f.open() as fh:
            for line in fh:
                m = pat.search(line)
                if m:
                    parts = line.split("|", 3)
                    s = max(0, m.start() - 60)
                    print(f"[{game}/{f.stem}] {parts[0]}|{parts[1] if len(parts) > 1 else ''} …{line[s:m.end() + 60].strip()}…")
                    n += 1
                    if n >= (a.n or 60):
                        print("... (limit reached; narrow with -f/-g or a tighter regex)")
                        return


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
