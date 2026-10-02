#!/usr/bin/env python3
"""Extract the Cypher System SRD from the mrkwnzl/cyphersystem-compendium release.zip (a Foundry VTT
module whose packs are LevelDB databases) into compact, grep-friendly text files: one record per line,
pipe-delimited, labeled fields."""
import argparse
import html
import io
import json
import re
import struct
import sys
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict

REPO = "mrkwnzl/cyphersystem-compendium"
ASSET = "release.zip"
UA = {"User-Agent": "ork-gaming-skills-extract"}

ID_NAME: Dict[str, str] = {}


def asset_url(tag: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{tag}/{ASSET}"


def fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"error: {url}: HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"error: {url}: {e.reason}")


def latest_tag() -> str:
    """Newest non-draft, non-prerelease tag that has a release.zip."""
    for r in json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases?per_page=20")):
        if not r.get("draft") and not r.get("prerelease") and any(x["name"] == ASSET for x in r.get("assets", [])):
            return r["tag_name"]
    sys.exit(f"error: no release with {ASSET} found")


def open_zip(tag: str) -> zipfile.ZipFile:
    """Download a release's release.zip into memory (never written to disk)."""
    data = fetch(asset_url(tag))
    print(f"{tag}: {len(data) / 1e6:.1f} MB", file=sys.stderr)
    return zipfile.ZipFile(io.BytesIO(data))


# ---------------------------------------------------------------- LevelDB (read-only, stdlib)

def varint(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def snappy(b):
    _, i = varint(b, 0)
    out = bytearray()
    while i < len(b):
        t = b[i]
        i += 1
        k = t & 3
        if k == 0:  # literal
            n = t >> 2
            if n >= 60:
                nb = n - 59
                n = int.from_bytes(b[i:i + nb], "little")
                i += nb
            n += 1
            out += b[i:i + n]
            i += n
            continue
        if k == 1:
            n, off = ((t >> 2) & 7) + 4, ((t >> 5) << 8) | b[i]
            i += 1
        elif k == 2:
            n, off = (t >> 2) + 1, int.from_bytes(b[i:i + 2], "little")
            i += 2
        else:
            n, off = (t >> 2) + 1, int.from_bytes(b[i:i + 4], "little")
            i += 4
        for _ in range(n):  # copies may overlap their own output
            out.append(out[-off])
    return bytes(out)


def read_block(b, off, size):
    raw = b[off:off + size]
    ctype = b[off + size]
    if ctype == 0:
        return raw
    if ctype == 1:
        return snappy(raw)
    raise ValueError(f"unsupported LevelDB block compression {ctype}")


def block_entries(blk):
    restarts = struct.unpack("<I", blk[-4:])[0]
    end = len(blk) - 4 - 4 * restarts
    i, key = 0, b""
    while i < end:
        shared, i = varint(blk, i)
        unshared, i = varint(blk, i)
        vlen, i = varint(blk, i)
        key = key[:shared] + blk[i:i + unshared]
        i += unshared
        yield key, blk[i:i + vlen]
        i += vlen


def sstable(b):
    """Yield (key, seq, type, value) from an .ldb table file."""
    footer = b[-48:]
    _, i = varint(footer, 0)  # metaindex handle
    _, i = varint(footer, i)
    ioff, i = varint(footer, i)
    isize, i = varint(footer, i)
    for _, handle in block_entries(read_block(b, ioff, isize)):
        off, j = varint(handle, 0)
        size, _ = varint(handle, j)
        for ikey, v in block_entries(read_block(b, off, size)):
            tag = int.from_bytes(ikey[-8:], "little")
            yield ikey[:-8], tag >> 8, tag & 0xFF, v


def wal(b):
    """Yield (key, seq, type, value) from a .log write-ahead log."""
    BLOCK = 32768
    i, rec = 0, b""
    while i + 7 <= len(b):
        if BLOCK - i % BLOCK < 7:  # block trailer padding
            i += BLOCK - i % BLOCK
            continue
        n, t = struct.unpack("<H", b[i + 4:i + 6])[0], b[i + 6]
        if t == 0:  # zero padding / preallocated space
            i += BLOCK - i % BLOCK
            continue
        rec += b[i + 7:i + 7 + n]
        i += 7 + n
        if t in (1, 4):  # FULL or LAST fragment: a complete WriteBatch
            seq, count = struct.unpack("<QI", rec[:12])
            j = 12
            for k in range(count):
                kind = rec[j]
                kl, j = varint(rec, j + 1)
                key = rec[j:j + kl]
                j += kl
                v = None
                if kind == 1:
                    vl, j = varint(rec, j)
                    v = rec[j:j + vl]
                    j += vl
                yield key, seq + k, kind, v
            rec = b""


def read_pack(zf: zipfile.ZipFile, pack: str) -> Dict[str, dict]:
    """All live documents in packs/<pack>/, keyed by LevelDB key (e.g. '!items!<id>')."""
    best = {}
    for name in zf.namelist():
        m = re.fullmatch(rf"packs/{re.escape(pack)}/[^/]+\.(ldb|log)", name)
        if not m:
            continue
        data = zf.read(name)
        for key, seq, kind, v in (sstable(data) if m.group(1) == "ldb" else wal(data)):
            if key not in best or seq > best[key][0]:
                best[key] = (seq, kind, v)
    return {k.decode(): json.loads(v) for k, (_, kind, v) in sorted(best.items()) if kind == 1}


def packs(zf: zipfile.ZipFile):
    return sorted({m.group(1) for n in zf.namelist() for m in [re.match(r"packs/([^/]+)/", n)] if m})


# ---------------------------------------------------------------- text

def _link(m):
    ref, label = m.group(1), m.group(2)
    if label:
        return label
    last = ref.split(".")[-1]
    return ID_NAME.get(last, last)


def _roll(m):
    return m.group(2) or m.group(1).split("#")[0].strip()


LABEL = r"(?:\{([^}]*)\})?"
ENRICHERS = [
    (re.compile(r"@UUID\[([^\]]+)\]" + LABEL), _link),
    (re.compile(r"@Compendium\[([^\]]+)\]" + LABEL), _link),
    (re.compile(r"\[\[/\w+ ((?:[^\[\]]|\[[^\]]*\])*)\]\]" + LABEL), _roll),
    (re.compile(r"@(\w+)\[([^\]]+)\]" + LABEL), lambda m: m.group(3) or m.group(2).split("|")[0]),
]

TAG_BLOCK = re.compile(r"</?(p|div|li|ul|ol|h[1-6]|tr|table|thead|tbody|section|blockquote)\b[^>]*>", re.I)


def clean(s) -> str:
    if not s or not isinstance(s, str):
        return ""
    for rx, fn in ENRICHERS:
        s = rx.sub(fn, s)
    s = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r" /[\1]/ ", s, flags=re.S | re.I)
    s = re.sub(r"<hr\s*/?>", " / ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", " / ", s, flags=re.I)
    s = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", ",", s, flags=re.I)
    s = re.sub(r"</tr>", ";", s, flags=re.I)
    s = TAG_BLOCK.sub(" / ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("|", "¦")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r" ([,.;:)])", r"\1", s)
    s = re.sub(r"(\s*/\s*)+", " / ", s)
    s = re.sub(r"\s*;\s*(/\s*)?", "; ", s)
    return s.strip(" /;")


def rec(*fields) -> str:
    return "|".join(str(f) for f in fields if f not in (None, ""))


def lab(k, v):
    v = clean(str(v)) if v not in (None, "") else ""
    return f"{k}:{v}" if v else ""


# ---------------------------------------------------------------- formatters

GENRES = {"fantasy", "modern", "modern-fantasy", "sci-fi", "post-apocalyptic", "horror", "fairy-tale",
          "superhero", "power-boost"}


def genre(pack):
    for g in sorted(GENRES, key=len, reverse=True):
        if pack.endswith("-" + g):
            return lab("genre", g)
    return ""


def num(v):
    """Drop zero/empty numbers."""
    return "" if v in (None, "", 0, "0") else v


def strip_level(text):
    return re.sub(r"^Level:\s*[^/]*/\s*", "", text)


def f_ability(d, s, pack):
    b = s.get("basic") or {}
    cost = num(b.get("cost"))
    pool = b.get("pool")
    c = f"{cost} {pool}" if cost and pool in ("Might", "Speed", "Intellect") else cost
    src = pack if pack != "abilities" else ""
    return rec(d["name"], "ability", lab("cost", c), lab("pack", src), genre(pack), clean(s.get("description")))


def f_skill(d, s, pack):
    r = (s.get("basic") or {}).get("rating", "")
    return rec(d["name"], "inability" if r == "Inability" else "skill", lab("rating", r.lower()),
               lab("pack", pack), clean(s.get("description")))


def f_cypher(d, s, pack):
    b = s.get("basic") or {}
    return rec(d["name"], "cypher", lab("level", b.get("level")), genre(pack), strip_level(clean(s.get("description"))))


def f_artifact(d, s, pack):
    b = s.get("basic") or {}
    dep = clean(b.get("depletion"))
    return rec(d["name"], "artifact", lab("level", b.get("level")), lab("depletion", "" if dep in ("—", "-") else dep),
               genre(pack), strip_level(clean(s.get("description"))))


def f_equipment(d, s, pack):
    b = s.get("basic") or {}
    p = s.get("price") or {}
    q = b.get("quantity")
    return rec(d["name"], d["type"], lab("level", num(b.get("level"))), lab("price", p.get("category") or p.get("priceTag")),
               lab("qty", "" if str(q) in ("1", "None") else q), genre(pack), clean(s.get("description")))


def f_attack(d, s, pack):
    b = s.get("basic") or {}
    w = (b.get("type") or "").replace(" weapon", "")
    return rec(d["name"], "weapon", lab("weapon", "" if w == "n/a" else w), lab("damage", num(b.get("damage"))),
               lab("range", b.get("range")), lab("notes", b.get("notes")), genre(pack), clean(s.get("description")))


def f_armor(d, s, pack):
    b = s.get("basic") or {}
    a = (b.get("type") or "").replace(" armor", "")
    return rec(d["name"], "armor", lab("armor", "" if a == "n/a" else a), lab("rating", num(b.get("rating"))),
               lab("cost", num(b.get("cost"))), lab("notes", b.get("notes")), genre(pack), clean(s.get("description")))


def f_power_shift(d, s, pack):
    return rec(d["name"], "power shift", clean(s.get("description")))


def f_npc(d, s, pack):
    b = s.get("basic") or {}
    c = s.get("combat") or {}
    lvl = b.get("level")
    lv = f"{lvl} (target {int(lvl) * 3})" if isinstance(lvl, int) or str(lvl).isdigit() else lvl
    text = " / ".join(x for x in (clean(b.get("biography")), clean(s.get("description")), clean(s.get("notes"))) if x)
    return rec(d["name"], "creature", lab("level", lv), lab("health", (s.get("pools") or {}).get("health", {}).get("max")),
               lab("damage", c.get("damage")), lab("armor", num(c.get("armor"))), lab("pack", pack), text)


def f_vehicle(d, s, pack):
    b = s.get("basic") or {}
    return rec(d["name"], "starship" if pack == "starships" else "vehicle", lab("level", b.get("level")),
               lab("crew", b.get("crew")), lab("weapons", num(b.get("weaponSystems"))), clean(s.get("notes")))


FORMATTERS = {
    "ability": f_ability, "skill": f_skill, "cypher": f_cypher, "artifact": f_artifact,
    "equipment": f_equipment, "material": f_equipment, "ammo": f_equipment, "attack": f_attack,
    "armor": f_armor, "power-shift": f_power_shift, "npc": f_npc, "vehicle": f_vehicle,
}
FILES = {
    "ability": "abilities", "skill": "skills", "cypher": "cyphers", "artifact": "artifacts",
    "equipment": "equipment", "material": "equipment", "ammo": "equipment", "attack": "weapons",
    "armor": "armor", "power-shift": "power-shifts", "npc": "creatures", "vehicle": "vehicles",
}
# journals whose pages are character options, so lookups by bare name find them
OPTION_KIND = {"Type": "type", "Descriptor": "descriptor", "Focus": "focus", "Flavor": "flavor", "Abilities": "ability"}


def journal_lines(docs, folders):
    pages = {k.split("!", 2)[2]: v for k, v in docs.items() if k.startswith("!journal.pages!")}

    def path(fid):
        out = []
        while fid in folders:
            out.insert(0, folders[fid]["name"])
            fid = folders[fid].get("folder")
        return " > ".join(out)

    for k, j in docs.items():
        if not k.startswith("!journal!"):
            continue
        book = path(j.get("folder"))
        kind = OPTION_KIND.get(j["name"]) if book.endswith("Characters") else None
        for n, pid in enumerate(j.get("pages") or []):
            p = pages.get(f"{j['_id']}.{pid}")
            txt = clean(((p or {}).get("text") or {}).get("content"))
            if not txt:
                continue
            first = n == 0 and p["name"] == j["name"]
            name = j["name"] if first else f"{j['name']} > {p['name']}"
            yield name, (kind if kind and not first else "rules"), rec(name, kind if kind and not first else "rules", lab("book", book), txt)


def table_lines(docs):
    results = {k.split("!", 2)[2]: v for k, v in docs.items() if k.startswith("!tables.results!")}
    for k, t in docs.items():
        if not k.startswith("!tables!"):
            continue
        res = []
        for rid in t.get("results") or []:
            r = results.get(f"{t['_id']}.{rid}")
            if not r:
                continue
            lo, hi = r.get("range") or [0, 0]
            v = clean(r.get("text")) or ID_NAME.get(r.get("documentId") or "", "")
            res.append(f"{lo if lo == hi else f'{lo}-{hi}'}:{v}")
        res.sort(key=lambda x: int(re.match(r"\d+", x).group()) if re.match(r"\d+", x) else 0)
        yield t["name"], rec(t["name"], "table", lab("roll", t.get("formula")), clean(t.get("description")), "; ".join(res))


# ---------------------------------------------------------------- main

def check(out: Path) -> int:
    """Compare the installed tag in out/VERSION against the latest release. Returns 1 if outdated."""
    vf = out / "VERSION"
    have = vf.read_text(encoding="utf-8").split()[0] if vf.exists() and vf.read_text(encoding="utf-8").strip() else None
    new = latest_tag()
    print(f"cypher: installed {have or 'none'}, latest {new} ({'up to date' if have == new else 'update available'})")
    return 0 if have == new else 1


def main():
    ap = argparse.ArgumentParser(description=f"Extract the Cypher SRD from {REPO} release {ASSET}.")
    ap.add_argument("--tag", metavar="TAG", help="release tag, e.g. v3.12.1 or 3.12.1 (default: latest)")
    ap.add_argument("--out", default=Path(__file__).resolve().parent / "skill" / "cypher" / "data", type=Path,
                    help="output directory (default: skill/cypher/data next to this script)")
    ap.add_argument("--check", action="store_true", help="compare installed data with the latest release and exit")
    a = ap.parse_args()
    if a.check:
        sys.exit(check(a.out))
    tag = a.tag or latest_tag()
    tag = tag if tag.startswith("v") else f"v{tag}"
    zf = open_zip(tag)
    db = {p: read_pack(zf, p) for p in packs(zf)}
    for docs in db.values():
        for d in docs.values():
            if "_id" in d and "name" in d:
                ID_NAME[d["_id"]] = d["name"]
    files = defaultdict(list)
    index = []
    stats = Counter()
    for pack, docs in db.items():
        folders = {v["_id"]: v for k, v in docs.items() if k.startswith("!folders!")}
        for name, kind, line in journal_lines(docs, folders):
            files["rules"].append(line)
            index.append(rec(name, kind, "rules"))
            stats["journal page"] += 1
        for name, line in table_lines(docs):
            files["tables"].append(line)
            index.append(rec(name, "table", "tables"))
            stats["table"] += 1
        for k, d in docs.items():
            t = d.get("type")
            if not re.match(r"!(items|actors)!", k):
                continue
            if t not in FORMATTERS:
                stats[f"skipped:{t}"] += 1
                continue
            line = FORMATTERS[t](d, d.get("system") or {}, pack)
            fname = FILES[t]
            files[fname].append(line)
            index.append(rec(d["name"], line.split("|")[1], fname))
            stats[t] += 1
    a.out.mkdir(parents=True, exist_ok=True)
    for old in a.out.glob("*.txt"):
        old.unlink()
    for fname, lines in files.items():
        lines.sort(key=str.lower)
        (a.out / f"{fname}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    index.sort(key=str.lower)
    (a.out / "index.txt").write_text("\n".join(index) + "\n", encoding="utf-8")
    (a.out / "VERSION").write_text(f"{tag} {asset_url(tag)}\n", encoding="utf-8")
    for k, v in sorted(stats.items()):
        print(f"{v:6} {k}")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
