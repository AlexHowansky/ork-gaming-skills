#!/usr/bin/env python3
"""Look up D&D 5e SRD records (2024 SRD 5.2 and 2014 SRD 5.1) extracted from the foundryvtt/dnd5e system.

  dnd5e.py NAME [NAME...]     records whose name matches (exact or last ' > ' part, then prefix, then substring)
  dnd5e.py -s REGEX           list names of records whose text matches (full-text search)
options: -e 2024|2014  -f FILE (e.g. spells, monsters, rules)  -n MAX (default 5 records / 60 search hits)
         -r (raw one-line output)
"""
import argparse
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
EDITIONS = ("2024", "2014")  # 2024 first


def files(edition, fname):
    for ed in EDITIONS:
        ed_dir = DATA / ed
        if (edition and ed != edition) or not ed_dir.is_dir():
            continue
        for f in sorted(ed_dir.glob("*.txt")):
            if f.stem == "index" or (fname and f.stem != fname):
                continue
            yield ed, f


def records(edition=None, fname=None):
    """Yield (edition, file stem, line) for every record, streaming from disk."""
    for ed, f in files(edition, fname):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                yield ed, f.stem, line.rstrip("\n")


def rank(recs, name):
    """Records whose name matches: exact (or exact last ' > ' part) if any, else prefix, else substring
    (case-insensitive)."""
    q = name.lower()
    tiers = ([], [], [])
    for r in recs:
        n = r[2].split("|", 1)[0].lower()
        if n == q or n.rsplit(" > ", 1)[-1] == q:
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


def show(ed, stem, line, raw):
    if raw:
        print(f"[{ed} {stem}] {line}")
        return
    parts = line.split("|")
    print(f"== {parts[0]}  [{ed} {stem}] {parts[1]}")
    for p in parts[2:]:
        print("  " + p.replace(" / ", "\n    "))


def lookup(names, a):
    n = a.n or 5
    for name in names:
        hits = rank(records(a.e, a.f), name)
        if not hits:
            print(f"no match: {name}")
        for h in hits[:n]:
            show(*h, a.r)
        if len(hits) > n:
            print(f"... {len(hits) - n} more: " + "; ".join(
                "%s [%s %s]" % (h[2].split("|", 1)[0], h[0], h[1]) for h in hits[n:][:40]))


def search(rx, a):
    n = a.n or 60
    hits = grep(records(a.e, a.f), rx, n)
    for (ed, stem, line), m in hits:
        s = max(0, m.start() - 60)
        print(f"[{ed} {stem}] {'|'.join(line.split('|', 2)[:2])} …{line[s:m.end() + 60].strip()}…")
    if len(hits) >= n:
        print("... (limit reached; narrow with -e/-f or a tighter regex)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("terms", nargs="+")
    ap.add_argument("-s", action="store_true", help="full-text regex search")
    ap.add_argument("-e", choices=EDITIONS, help="edition: 2024 (SRD 5.2) or 2014 (SRD 5.1)")
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
