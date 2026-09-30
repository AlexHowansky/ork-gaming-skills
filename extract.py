#!/usr/bin/env python3
"""Extract PF2e/SF2e compendium data from the foundryvtt/pf2e release json-assets.zip files
into compact, grep-friendly text files: one record per line, pipe-delimited, labeled fields."""
import argparse
import html
import io
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------- lookups

ID_NAME: dict[str, str] = {}
LANG: dict[str, str] = {}
SOURCES: dict[str, str] = {}  # lowercased publication title -> short code
TITLES: dict[str, str] = {}  # short code -> publication title

SIZES = {"tiny": "tiny", "sm": "sm", "med": "med", "lg": "lg", "huge": "huge", "grg": "garg"}
ACTS = {"1": "1a", "2": "2a", "3": "3a", "reaction": "r", "free": "f"}
DMG = {"slashing": "S", "piercing": "P", "bludgeoning": "B"}
BULK = {0: "-", 0.1: "L"}
ABBR_SKIP = {"pathfinder", "starfinder", "the", "of", "and", "a", "in", "to", "for", "at"}


REPO = "foundryvtt/pf2e"
GAMES = ("pf2e", "sf2e")
ASSET = "json-assets.zip"
UA = {"User-Agent": "ork-pf2e-tools-extract"}


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


def latest_tags() -> dict[str, str]:
    """Newest non-draft, non-prerelease tag per game that has a json-assets.zip."""
    releases = json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases?per_page=50"))
    tags = {}
    for r in releases:
        if r.get("draft") or r.get("prerelease") or not any(x["name"] == ASSET for x in r.get("assets", [])):
            continue
        for game in GAMES:
            if game not in tags and re.match(rf"{game}-\d", r["tag_name"]):
                tags[game] = r["tag_name"]
    missing = [g for g in GAMES if g not in tags]
    if missing:
        sys.exit(f"error: no release with {ASSET} found for {', '.join(missing)}")
    return tags


def open_zip(tag: str) -> zipfile.ZipFile:
    """Download a release's json-assets.zip into memory (never written to disk)."""
    data = fetch(asset_url(tag))
    print(f"{tag}: {len(data) / 1e6:.1f} MB", file=sys.stderr)
    return zipfile.ZipFile(io.BytesIO(data))


def load_lang(zf: zipfile.ZipFile):
    def flat(o, p):
        if isinstance(o, dict):
            for k, v in o.items():
                flat(v, f"{p}.{k}" if p else k)
        elif isinstance(o, str):
            LANG[p] = o

    for name in sorted(zf.namelist()):
        if not re.fullmatch(r"lang/[^/]+\.json", name) or "sf2e-overrides" in name:
            continue
        flat(json.loads(zf.read(name)), "")


CURATED = {
    "pathfinder core rulebook": "CRB", "pathfinder advanced player's guide": "APG", "pathfinder bestiary": "B1",
    "pathfinder bestiary 2": "B2", "pathfinder bestiary 3": "B3", "pathfinder gamemastery guide": "GMG",
    "pathfinder guns & gears": "G&G", "pathfinder secrets of magic": "SoM", "pathfinder book of the dead": "BotD",
    "pathfinder dark archive": "DA", "pathfinder dark archive (remastered)": "DA-R", "pathfinder treasure vault": "TV",
    "pathfinder treasure vault (remastered)": "TV-R", "pathfinder rage of elements": "RoE",
    "pathfinder player core": "PC1", "pathfinder player core 2": "PC2", "pathfinder gm core": "GMC",
    "pathfinder monster core": "MC1", "pathfinder monster core 2": "MC2", "pathfinder npc core": "NPCC",
    "pathfinder howl of the wild": "HotW", "pathfinder war of immortals": "WoI", "pathfinder battlecry!": "BC",
    "pathfinder impossible magic": "IM", "pathfinder beginner box": "BB", "pathfinder blog": "Blog",
    "pathfinder kingmaker": "KM", "pathfinder adventure path: gatewalkers": "AP-GW",
    "starfinder player core": "SF-PC", "starfinder gm core": "SF-GMC", "starfinder alien core": "SF-AC",
    "starfinder galaxy guide": "SF-GG", "starfinder galactic ancestries": "SF-GA", "tales from the vast": "SF-TftV",
}


def source_code(title: str) -> str:
    title = title.strip()
    key = title.lower()
    if not title:
        return ""
    if key in SOURCES:
        return SOURCES[key]
    if key in CURATED:
        SOURCES[key] = CURATED[key]
        TITLES[CURATED[key]] = title
        return CURATED[key]
    words = re.findall(r"[A-Za-z0-9]+", title)
    ab = "".join(w[0].upper() if not w.isdigit() else w for w in words if w.lower() not in ABBR_SKIP)
    if title.lower().startswith("starfinder"):
        ab = "S" + ab
    ab = ab or "X"
    code, n = ab, 2
    used = set(SOURCES.values()) | set(CURATED.values())
    while code in used:
        code, n = f"{ab}{n}", n + 1
    SOURCES[key] = code
    TITLES[code] = title
    return code


# ---------------------------------------------------------------- text cleanup

def _check(m):
    body, label = m.group(1), m.group(2)
    if label:
        return label
    parts = body.split("|")
    kv = {}
    typ = ""
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            kv[k.strip()] = v.strip()
        elif not typ:
            typ = p.strip()
    typ = kv.get("type", typ)
    out = []
    if "dc" in kv:
        out.append(f"DC {kv['dc']}")
    if kv.get("basic") == "true":
        out.append("basic")
    out.append(typ.replace("-", " ").title() if typ else "check")
    return " ".join(out)


def _damage(m):
    body, label = m.group(1), m.group(2)
    if label:
        return label
    formula = body.split("|")[0]
    # 6d6[fire] -> 6d6 fire ; (2d6+4)[persistent,fire] -> (2d6+4) persistent fire
    for _ in range(3):
        formula = re.sub(r"\[([a-z,\-]+)\]", lambda x: " " + x.group(1).replace(",", " "), formula)
    return formula


def _template(m):
    body, label = m.group(1), m.group(2)
    if label:
        return label
    kv, typ = {}, ""
    for p in body.split("|"):
        if ":" in p:
            k, v = p.split(":", 1)
            kv[k] = v
        elif not typ:
            typ = p
    typ = kv.get("type", typ)
    return f"{kv.get('distance', '')}ft {typ}".strip()


def _uuid(m):
    ref, label = m.group(1), m.group(2)
    if label:
        return label
    last = ref.split(".")[-1]
    return ID_NAME.get(last, last)


def _roll(m):
    body, label = m.group(1), m.group(2)
    if label:
        return label
    body = body.split("#")[0].strip()
    return re.sub(r"\[([a-z,]+)\]", lambda x: " " + x.group(1).replace(",", " "), body)


LABEL = r"(?:\{([^}]*)\})?"
ENRICHERS = [
    (re.compile(r"@UUID\[([^\]]+)\]" + LABEL), _uuid),
    (re.compile(r"@Compendium\[([^\]]+)\]" + LABEL), _uuid),
    (re.compile(r"@Check\[([^\]]+)\]" + LABEL), _check),
    (re.compile(r"@Damage\[((?:[^\[\]]|\[[^\]]*\])+)\]" + LABEL), _damage),
    (re.compile(r"@Template\[([^\]]+)\]" + LABEL), _template),
    (re.compile(r"@Localize\[([^\]]+)\]" + LABEL), lambda m: m.group(2) or clean(LANG.get(m.group(1), ""))),
    (re.compile(r"@Embed\[[^\]]*\]" + LABEL), lambda m: ""),
    (re.compile(r"\[\[/\w+ ((?:[^\[\]]|\[[^\]]*\])*)\]\]" + LABEL), _roll),
    (re.compile(r"@(\w+)\[([^\]]+)\]" + LABEL), lambda m: m.group(3) or m.group(2).split("|")[0]),
]

TAG_BLOCK = re.compile(r"</?(p|div|li|ul|ol|h[1-6]|tr|table|thead|tbody|section|blockquote)\b[^>]*>", re.I)


def clean(s) -> str:
    if not s or not isinstance(s, str):
        return ""
    for _ in range(2):  # enrichers can nest (@Localize -> @UUID)
        for rx, fn in ENRICHERS:
            s = rx.sub(fn, s)
    s = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r" /[\1]/ ", s, flags=re.S | re.I)
    s = re.sub(r"<hr\s*/?>", " / ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", " / ", s, flags=re.I)
    s = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", ",", s, flags=re.I)
    s = re.sub(r"</tr>", ";", s, flags=re.I)
    s = TAG_BLOCK.sub(" / ", s)
    s = re.sub(r"</(span|a|td|th|footer|header|aside|figure|figcaption)>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("|", "¦")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r" ([,.;:)])", r"\1", s)
    s = re.sub(r"(\s*/\s*)+", " / ", s)
    s = re.sub(r"\s*;\s*(/\s*)?", "; ", s)
    return s.strip(" /;")


# ---------------------------------------------------------------- helpers

def g(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
        if d is None:
            return default
    return d


def fmt_mod(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"+{n}" if n >= 0 else str(n)


def traits(sys_):
    t = g(sys_, "traits") or {}
    vals = list(t.get("value") or []) if isinstance(t, dict) else []
    rar = t.get("rarity") if isinstance(t, dict) else None
    if rar and rar != "common":
        vals.insert(0, rar)
    return ",".join(vals)


def pub(sys_):
    p = g(sys_, "publication") or g(sys_, "details", "publication") or {}
    code = source_code(p.get("title", ""))
    if p.get("remaster"):
        code += " R"
    return code.strip()


def price(p):
    v = g(p, "value") or {}
    s = " ".join(f"{v[k]}{k}" for k in ("pp", "gp", "sp", "cp", "credits", "upb") if v.get(k))
    if p and p.get("per", 1) not in (1, None):
        s += f"/{p['per']}"
    return s


def bulk(b):
    v = g(b, "value")
    if v is None:
        return ""
    return BULK.get(v, str(v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v))


def acts(sys_):
    at = g(sys_, "actionType", "value")
    if at in ("reaction", "free"):
        return ACTS[at]
    if at == "action":
        return ACTS.get(str(g(sys_, "actions", "value") or 1), "")
    return ""


def freq(sys_):
    f = g(sys_, "frequency")
    if not f or not f.get("max"):
        return ""
    return f"{f['max']}/{f.get('per', '')}"


def iwr(attrs):
    out = []
    for key, lab in (("immunities", "imm"), ("weaknesses", "weak"), ("resistances", "res")):
        items = attrs.get(key) or []
        parts = []
        for i in items:
            s = i.get("type", "").replace("-", " ")
            if i.get("value") is not None:
                s += f" {i['value']}"
            if i.get("exceptions"):
                s += " (except " + ",".join(e if isinstance(e, str) else e.get("label", "") for e in i["exceptions"]) + ")"
            if i.get("doubleVs"):
                s += " (double vs " + ",".join(i["doubleVs"]) + ")"
            parts.append(s)
        if parts:
            out.append(f"{lab}:" + ",".join(parts))
    return out


def speeds(attrs, sys_):
    sp = attrs.get("speed") or g(sys_, "movement", "speeds") or {}
    out = []
    if isinstance(sp, dict):
        if "value" in sp:
            out.append(str(sp["value"]))
        for o in sp.get("otherSpeeds") or []:
            out.append(f"{o.get('type')} {o.get('value')}")
        for k, v in sp.items():  # newer schema: {land:{value}, fly:{value}}
            if isinstance(v, dict) and "value" in v and v["value"]:
                out.append(f"{k} {v['value']}")
        if sp.get("details"):
            out.append(clean(sp["details"]))
    return ",".join(out)


def rec(*fields) -> str:
    return "|".join(str(f) for f in fields if f not in (None, "", [], "0ft"))


def lab(k, v):
    return f"{k}:{v}" if v not in (None, "", [], {}) else ""


# ---------------------------------------------------------------- formatters

def f_spell(d, s, pack):
    tr = (g(s, "traits", "value") or [])
    lvl = g(s, "level", "value")
    kind = "cantrip" if "cantrip" in tr else "focus" if "focus" in tr else "ritual" if g(s, "ritual") else "spell"
    tr = [t for t in tr if t not in ("cantrip",)]
    rar = g(s, "traits", "rarity")
    if rar and rar != "common":
        tr.insert(0, rar)
    dur = g(s, "duration", "value") or ""
    if g(s, "duration", "sustained"):
        dur = ("sustained " + dur).strip()
    area = g(s, "area")
    area = f"{area.get('value')}ft {area.get('type')}" if area else ""
    df = ""
    if g(s, "defense", "save"):
        sv = s["defense"]["save"]
        df = ("basic " if sv.get("basic") else "") + sv.get("statistic", "")
    elif g(s, "defense", "passive"):
        df = "vs " + s["defense"]["passive"].get("statistic", "")
    t = g(s, "time", "value") or ""
    t = ACTS.get(t, t)
    rit = g(s, "ritual")
    ritual = ""
    if rit:
        ritual = f"primary:{g(rit, 'primary', 'check')} secondary:{g(rit, 'secondary', 'casters')} {g(rit, 'secondary', 'checks')}"
    return rec(d["name"], f"{kind} {lvl}", pub(s),
               lab("trad", ",".join(g(s, "traits", "traditions") or [])), lab("tr", ",".join(tr)),
               lab("cast", t), lab("cost", g(s, "cost", "value")), lab("req", g(s, "requirements")),
               lab("rng", g(s, "range", "value")), lab("area", area), lab("tgt", g(s, "target", "value")),
               lab("def", df), lab("dur", dur), lab("ritual", ritual), clean(g(s, "description", "value")))


def prereqs(s):
    return "; ".join(p.get("value", "") for p in (g(s, "prerequisites", "value") or []))


def f_feat(d, s, pack):
    cat = g(s, "category") or ""
    kind = "feat" if cat in ("", "bonus") else cat if cat in ("classfeature", "ancestryfeature", "pfsboon", "deityboon", "curse") else f"{cat} feat"
    return rec(d["name"], f"{kind} {g(s, 'level', 'value')}", pub(s), lab("tr", traits(s)),
               lab("act", acts(s)), lab("prereq", prereqs(s)), lab("freq", freq(s)),
               lab("req", g(s, "requirements")), lab("trig", g(s, "trigger")),
               clean(g(s, "description", "value")))


def f_action(d, s, pack):
    return rec(d["name"], f"action {g(s, 'category') or ''}".strip(), pub(s), lab("tr", traits(s)),
               lab("act", acts(s)), lab("freq", freq(s)), clean(g(s, "description", "value")))


def f_item(d, s, pack):
    t = d["type"]
    extra = []
    if t == "weapon":
        dm = g(s, "damage") or {}
        die = f"{dm.get('dice', '')}{dm.get('die') or ''} {DMG.get(dm.get('damageType'), dm.get('damageType') or '')}".strip()
        extra += [lab("cat", f"{g(s, 'category') or ''} {g(s, 'group') or ''}".strip()), lab("dmg", die),
                  lab("rng", g(s, "range")), lab("reload", g(s, "reload", "value"))]
    elif t == "armor":
        extra += [lab("cat", f"{g(s, 'category') or ''} {g(s, 'group') or ''}".strip()), lab("AC", fmt_mod(g(s, "acBonus", default=0))),
                  lab("dexcap", g(s, "dexCap")), lab("chk", g(s, "checkPenalty") or ""),
                  lab("spd", g(s, "speedPenalty") or ""), lab("str", g(s, "strength") or "")]
    elif t == "shield":
        extra += [lab("AC", fmt_mod(g(s, "acBonus", default=0))), lab("hard", g(s, "hardness")),
                  lab("HP", g(s, "hp", "max")), lab("spd", g(s, "speedPenalty") or "")]
    elif t in ("consumable", "ammo"):
        extra += [lab("cat", g(s, "category")), lab("uses", g(s, "uses", "max") if (g(s, "uses", "max") or 0) > 1 else "")]
    if t in ("equipment", "backpack", "treasure", "kit"):
        extra.append(lab("cat", g(s, "category") if t == "treasure" else ""))
    return rec(d["name"], f"{t} {g(s, 'level', 'value', default='')}".strip(), pub(s), lab("tr", traits(s)),
               lab("price", price(g(s, "price"))), lab("bulk", bulk(g(s, "bulk"))),
               lab("usage", g(s, "usage", "value")), *extra, clean(g(s, "description", "value")))


def boosts(b):
    out = []
    for v in (b or {}).values():
        vals = v.get("value") or []
        out.append("/".join(vals) if len(vals) < 6 else "free")
    return ",".join(out)


def f_ancestry(d, s, pack):
    return rec(d["name"], "ancestry", pub(s), lab("tr", traits(s)), lab("hp", g(s, "hp")),
               lab("size", ",".join(SIZES.get(x, x) for x in (g(s, "size") or []))) if isinstance(g(s, "size"), list) else lab("size", g(s, "size")),
               lab("spd", g(s, "speed")), lab("boost", boosts(g(s, "boosts"))), lab("flaw", boosts(g(s, "flaws"))),
               lab("lang", ",".join(g(s, "languages", "value") or [])), lab("vision", g(s, "vision")),
               clean(g(s, "description", "value")))


def f_heritage(d, s, pack):
    return rec(d["name"], "heritage", pub(s), lab("anc", g(s, "ancestry", "name") or "versatile"),
               lab("tr", traits(s)), clean(g(s, "description", "value")))


def f_background(d, s, pack):
    sk = ",".join((g(s, "trainedSkills", "value") or []) + [f"{x} lore" for x in (g(s, "trainedSkills", "lore") or [])])
    feats = ",".join(i.get("name", "") for i in (g(s, "items") or {}).values())
    return rec(d["name"], "background", pub(s), lab("tr", traits(s)), lab("boost", boosts(g(s, "boosts"))),
               lab("skills", sk), lab("feat", feats), clean(g(s, "description", "value")))


RANK = "UTEML"


def ranks(o, prefix=""):
    if not isinstance(o, dict):
        return RANK[o] if isinstance(o, int) and 0 <= o < 5 else str(o or "")
    out = []
    for k, v in o.items():
        if isinstance(v, dict) and "rank" in v:
            if v.get("rank"):
                out.append(f"{v.get('name') or k} {RANK[v['rank']]}")
        elif isinstance(v, int) and v:
            out.append(f"{k} {RANK[v] if v < 5 else v}")
    return ",".join(out)


def f_class(d, s, pack):
    feats = "; ".join(f"{i.get('level')} {i.get('name')}" for i in sorted((g(s, "items") or {}).values(), key=lambda i: i.get("level", 0)))
    ts = g(s, "trainedSkills") or {}
    return rec(d["name"], "class", pub(s), lab("key", ",".join(g(s, "keyAbility", "value") or [])),
               lab("hp", g(s, "hp")), lab("perc", ranks(g(s, "perception"))), lab("saves", ranks(g(s, "savingThrows"))),
               lab("atk", ranks(g(s, "attacks"))), lab("def", ranks(g(s, "defenses"))),
               lab("skills", f"{','.join(ts.get('value') or [])} +{ts.get('additional')}"),
               lab("spellcasting", g(s, "spellcasting")), lab("features", feats), clean(g(s, "description", "value")))


def f_deity(d, s, pack):
    spells = ",".join(f"{lvl}:{ID_NAME.get(str(u).split('.')[-1], u)}" for lvl, u in (g(s, "spells") or {}).items())
    dom = g(s, "domains") or {}
    san = g(s, "sanctification") or {}
    return rec(d["name"], f"deity {g(s, 'category') or ''}".strip(), pub(s),
               lab("sanct", f"{san.get('modal', '')} {','.join(san.get('what') or [])}".strip() if san else ""),
               lab("font", ",".join(g(s, "font") or [])), lab("attr", ",".join(g(s, "attribute") or [])),
               lab("skill", ",".join(g(s, "skill") or []) if isinstance(g(s, "skill"), list) else g(s, "skill")),
               lab("weapon", ",".join(g(s, "weapons") or [])), lab("dom", ",".join(dom.get("primary") or [])),
               lab("altdom", ",".join(dom.get("alternate") or [])), lab("spells", spells), clean(g(s, "description", "value")))


def f_effect(d, s, pack):
    du = g(s, "duration") or {}
    dur = f"{du.get('value')} {du.get('unit')}" if du.get("value", -1) not in (-1, None) else du.get("unit", "")
    return rec(d["name"], f"{d['type']} {g(s, 'level', 'value', default='')}".strip(), pub(s), lab("tr", traits(s)),
               lab("dur", dur if dur not in ("unlimited", "encounter") else dur), clean(g(s, "description", "value")))


def f_campaign(d, s, pack):
    return rec(d["name"], f"{g(s, 'campaign')} {g(s, 'category')} {g(s, 'level', 'value', default='')}".strip(), pub(s),
               lab("tr", traits(s)), lab("act", acts(s)), lab("prereq", prereqs(s)),
               lab("req", g(s, "requirements")), clean(g(s, "description", "value")))


def strike(i):
    s = i["system"]
    dmg = " + ".join(f"{r.get('damage')} {r.get('category') + ' ' if r.get('category') else ''}{r.get('damageType')}"
                     for r in (g(s, "damageRolls") or {}).values())
    fx = g(s, "attackEffects", "value") or []
    if fx:
        dmg += " plus " + ",".join(x.replace("-", " ") for x in fx)
    rng = g(s, "range") or {}
    kind = "ranged" if rng else "melee"
    rs = f" rng{rng.get('increment') or rng.get('max')}" if rng else ""
    tr = ",".join(g(s, "traits", "value") or [])
    a = acts(s)
    return f"{kind} {a + ' ' if a else ''}{i['name']} {fmt_mod(g(s, 'bonus', 'value', default=0))}{rs}{' (' + tr + ')' if tr else ''} {dmg}".strip()


def ability(i):
    s = i["system"]
    a = acts(s)
    tr = traits(s)
    desc = clean(g(s, "description", "value"))
    head = i["name"] + (f" [{a}]" if a else "") + (f" ({tr})" if tr else "")
    return f"{head} {desc}".strip()


def spellcasting(items):
    entries = {i["_id"]: i for i in items if i["type"] == "spellcastingEntry"}
    spells = defaultdict(list)
    for i in items:
        if i["type"] == "spell":
            loc = g(i, "system", "location", "value")
            lvl = g(i, "system", "location", "heightenedLevel") or g(i, "system", "level", "value")
            if "cantrip" in (g(i, "system", "traits", "value") or []):
                lvl = f"C{g(i, 'system', 'location', 'heightenedLevel') or ''}"
            uses = g(i, "system", "location", "uses", "max")
            spells[loc].append((str(lvl), i["name"] + (f"({uses}/day)" if uses and uses > 1 else "")))
    out = []
    for eid, e in entries.items():
        s = e["system"]
        dc = g(s, "spelldc", "dc")
        atk = g(s, "spelldc", "value")
        by = defaultdict(list)
        for lvl, n in spells.get(eid, []):
            by[lvl].append(n)
        lst = "; ".join(f"{lvl} {','.join(ns)}" for lvl, ns in sorted(by.items(), key=lambda x: (not x[0].startswith("C"), x[0]), reverse=True))
        out.append(f"{e['name']} DC{dc} atk{fmt_mod(atk)}: {lst}".strip())
    return " // ".join(out)


GEAR = {"weapon", "armor", "shield", "equipment", "consumable", "treasure", "backpack", "ammo"}


def f_npc(d, s, pack):
    attrs = g(s, "attributes") or {}
    items = d.get("items") or []
    tr = traits(s)
    size = SIZES.get(g(s, "traits", "size", "value"), g(s, "traits", "size", "value") or "")
    perc = g(s, "perception") or {}
    senses = ",".join(
        (x.get("type", "") + (f" {x['acuity']}" if x.get("acuity") else "") + (f" {x['range']}" if x.get("range") else ""))
        for x in perc.get("senses") or [])
    percs = f"{fmt_mod(perc.get('mod'))}" + (f" {senses}" if senses else "") + (f" {clean(perc.get('details'))}" if perc.get("details") else "")
    langs = g(s, "details", "languages") or {}
    lang = ",".join(langs.get("value") or []) + (f" {clean(langs.get('details'))}" if langs.get("details") else "")
    skills = [f"{k} {fmt_mod(v.get('base'))}" for k, v in (g(s, "skills") or {}).items() if isinstance(v, dict)]
    skills += [f"{i['name']} {fmt_mod(g(i, 'system', 'mod', 'value'))}" for i in items if i["type"] == "lore"]
    ab = " ".join(f"{k}{fmt_mod(g(v, 'mod'))}" for k, v in (g(s, "abilities") or {}).items())
    sv = g(s, "saves") or {}
    saves = " ".join(f"{k[0].upper()}{fmt_mod(g(sv, k, 'value'))}" for k in ("fortitude", "reflex", "will") if k in sv)
    if g(attrs, "allSaves", "value"):
        saves += f" ({clean(attrs['allSaves']['value'])})"
    ac = f"AC{g(attrs, 'ac', 'value')}" + (f" ({clean(g(attrs, 'ac', 'details'))})" if g(attrs, "ac", "details") else "")
    hp = f"HP{g(attrs, 'hp', 'max')}" + (f" ({clean(g(attrs, 'hp', 'details'))})" if g(attrs, "hp", "details") else "")
    strikes = [strike(i) for i in items if i["type"] == "melee"]
    abil = [ability(i) for i in items if i["type"] == "action"]
    feats = [i["name"] for i in items if i["type"] == "feat"]
    gear = [i["name"] + (f" x{g(i, 'system', 'quantity')}" if (g(i, "system", "quantity") or 1) > 1 else "") for i in items if i["type"] in GEAR]
    blurb = g(s, "details", "blurb")
    return rec(d["name"], f"creature {g(s, 'details', 'level', 'value')}", pub(s), lab("pack", pack),
               lab("tr", ",".join(x for x in (size, tr) if x)), lab("blurb", blurb), lab("perc", percs), lab("lang", lang),
               lab("skills", ",".join(skills)), ab, f"{ac} {saves}", hp, *iwr(attrs), lab("spd", speeds(attrs, s)),
               *strikes, lab("spells", spellcasting(items)), *(f"ab:{a}" for a in abil),
               lab("feats", ",".join(feats)), lab("gear", ",".join(gear)))


def f_hazard(d, s, pack):
    attrs = g(s, "attributes") or {}
    det = g(s, "details") or {}
    items = d.get("items") or []
    stealth = f"{fmt_mod(g(attrs, 'stealth', 'value'))} {clean(g(attrs, 'stealth', 'details'))}".strip()
    sv = g(s, "saves") or {}
    saves = " ".join(f"{k[0].upper()}{fmt_mod(g(sv, k, 'value'))}" for k in ("fortitude", "reflex", "will") if g(sv, k, "value"))
    defs = ""
    if g(attrs, "ac", "value") or g(attrs, "hp", "max"):
        defs = f"AC{g(attrs, 'ac', 'value')} {saves} hard{attrs.get('hardness', 0)} HP{g(attrs, 'hp', 'max')}" + (
            f" ({clean(g(attrs, 'hp', 'details'))})" if g(attrs, "hp", "details") else "")
    return rec(d["name"], f"hazard {g(det, 'level', 'value')}" + (" complex" if det.get("isComplex") else ""), pub(s),
               lab("pack", pack), lab("tr", traits(s)), lab("stealth", stealth), lab("desc", clean(det.get("description"))),
               lab("disable", clean(det.get("disable"))), defs, *iwr(attrs),
               *(strike(i) for i in items if i["type"] == "melee"), *(f"ab:{ability(i)}" for i in items if i["type"] == "action"),
               lab("routine", clean(det.get("routine"))), lab("reset", clean(det.get("reset"))))


def flat_scalars(o, prefix="", out=None):
    out = [] if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("rules", "publication", "_stats", "flags", "img", "customModifiers", "tokenIcon", "privateNotes"):
                continue
            flat_scalars(v, f"{prefix}{k}." if not isinstance(v, (str, int, float, bool)) else f"{prefix}{k}", out)
    elif isinstance(o, list):
        if o and all(isinstance(x, (str, int, float)) for x in o):
            out.append(f"{prefix.rstrip('.')}:{','.join(map(str, o))}")
        else:
            for x in o:
                flat_scalars(x, prefix, out)
    elif o not in (None, "", False, 0):
        v = clean(o) if isinstance(o, str) else o
        if v not in ("", None):
            out.append(f"{prefix}:{v}")
    return out


def f_generic(d, s, pack):
    items = d.get("items") or []
    body = [re.sub(r"^(attributes|details)\.|\.value(?=:)|\.type(?=:)", "", x) for x in flat_scalars(s)
            if not x.startswith(("details.publication", "attributes.hp.value"))]
    return rec(d["name"], d["type"], pub(s), lab("pack", pack), *body,
               *(strike(i) for i in items if i["type"] == "melee"),
               *(f"ab:{ability(i)}" for i in items if i["type"] == "action"))


def f_character(d, s, pack):
    items = d.get("items") or []
    by = defaultdict(list)
    for i in items:
        by[i["type"]].append(i["name"])
    lvl = g(s, "details", "level", "value")
    head = ",".join(n for t in ("ancestry", "heritage", "background", "class") for n in by.get(t, []))
    return rec(d["name"], f"pregen {lvl}", lab("pack", pack), head, lab("feats", ",".join(by.get("feat", []))),
               lab("spells", ",".join(by.get("spell", []))),
               lab("gear", ",".join(n for t in GEAR for n in by.get(t, []))))


# ---------------------------------------------------------------- routing

ITEM_TYPES = {"weapon", "armor", "shield", "equipment", "consumable", "treasure", "backpack", "ammo", "kit"}
FORMATTERS = {
    "spell": ("spells", f_spell), "feat": ("feats", f_feat), "action": ("actions", f_action),
    "ancestry": ("ancestries", f_ancestry), "heritage": ("heritages", f_heritage), "background": ("backgrounds", f_background),
    "class": ("classes", f_class), "deity": ("deities", f_deity), "effect": ("effects", f_effect),
    "condition": ("conditions", f_effect), "campaignFeature": ("campaign", f_campaign),
    "npc": ("creatures", f_npc), "hazard": ("hazards", f_hazard), "vehicle": ("vehicles", f_generic),
    "army": ("campaign", f_generic), "familiar": ("pregens", f_generic), "character": ("pregens", f_character),
    "melee": ("creature-abilities", lambda d, s, p: strike(d) + "|" + pub(s)),
}
PACK_FILE = {
    "class-features": "class-features", "ancestry-features": "ancestry-features",
    "bestiary-ability-glossary-srd": "creature-abilities", "bestiary-family-ability-glossary": "creature-abilities",
    "familiar-abilities": "familiar-abilities", "boons-and-curses": "boons-and-curses",
    "pathfinder-society-boons": "society-boons", "starfinder-society-boons": "society-boons",
    "criticaldeck": "critical-deck", "adventure-specific-actions": "actions",
}


def route(doc, pack):
    t = doc.get("type")
    if t in ITEM_TYPES:
        return "equipment", f_item
    if t in FORMATTERS:
        fname, fn = FORMATTERS[t]
        if pack in PACK_FILE and t not in ("npc", "hazard"):
            fname = PACK_FILE[pack]
        return fname, fn
    return None, None


def journal_lines(doc, pack):
    for p in doc.get("pages") or []:
        txt = g(p, "text", "content")
        if not txt:
            continue
        yield rec(f"{doc['name']} > {p['name']}", "rules", lab("pack", pack), clean(txt))


def table_line(doc):
    res = []
    for r in doc.get("results") or []:
        rng = r.get("range") or [0, 0]
        k = str(rng[0]) if rng[0] == rng[1] else f"{rng[0]}-{rng[1]}"
        v = clean(r.get("description") or r.get("name") or r.get("text") or "")
        if not v and r.get("documentUuid"):
            v = ID_NAME.get(r["documentUuid"].split(".")[-1], "")
        res.append(f"{k}:{v}")
    return rec(doc["name"], "table", lab("roll", doc.get("formula")), clean(doc.get("description")), "; ".join(res))


# ---------------------------------------------------------------- main

def iter_docs(zf: zipfile.ZipFile):
    for name in sorted(zf.namelist()):
        m = re.fullmatch(r"packs/([^/]+)\.json", name)
        if not m or m.group(1).endswith("_folders"):
            continue
        try:
            docs = json.loads(zf.read(name))
        except json.JSONDecodeError as e:
            print(f"skip {name}: {e}", file=sys.stderr)
            continue
        for d in docs if isinstance(docs, list) else [docs]:
            if isinstance(d, dict):
                yield m.group(1), d


def build_names(zips):
    for zf in zips.values():
        for pack, d in iter_docs(zf):
            if "_id" in d and "name" in d:
                ID_NAME[d["_id"]] = d["name"]
            for sub in (d.get("items") or []) + (d.get("pages") or []):
                if isinstance(sub, dict) and "_id" in sub:
                    ID_NAME[sub["_id"]] = sub.get("name", "")


def check(out: Path) -> int:
    """Compare the installed tags in out/VERSION against the latest releases. Returns 1 if any are outdated."""
    vf = out / "VERSION"
    tags = [line.split()[0] for line in vf.read_text().splitlines() if line.strip()] if vf.exists() else []
    installed = {t.split("-", 1)[0]: t for t in tags}
    latest = latest_tags()
    stale = False
    for game in GAMES:
        have, new = installed.get(game), latest[game]
        status = "up to date" if have == new else "update available"
        stale |= have != new
        print(f"{game}: installed {have or 'none'}, latest {new} ({status})")
    return 1 if stale else 0


def main():
    ap = argparse.ArgumentParser(description=f"Extract from {REPO} release {ASSET} files.")
    for game in GAMES:
        ap.add_argument(f"--{game}", metavar="TAG", help=f"release tag, e.g. {game}-8.5.1 or 8.5.1 (default: latest)")
    ap.add_argument("--out", default="skill/pf2e-rules/data", type=Path)
    ap.add_argument("--check", action="store_true", help="compare installed data with the latest releases and exit")
    a = ap.parse_args()
    if a.check:
        sys.exit(check(a.out))
    tags = {g: getattr(a, g) for g in GAMES}
    if not all(tags.values()):
        latest = latest_tags()
        tags = {g: t or latest[g] for g, t in tags.items()}
    tags = {g: t if t.startswith(f"{g}-") else f"{g}-{t}" for g, t in tags.items()}
    zips = {g: open_zip(t) for g, t in tags.items()}
    load_lang(zips["pf2e"])
    build_names(zips)
    stats = Counter()
    for game in GAMES:
        files = defaultdict(list)
        index = []
        for pack, d in iter_docs(zips[game]):
            t = d.get("type")
            if t is None and "pages" in d:
                fname = "critical-deck" if pack == "criticaldeck" else "rules"
                for line in journal_lines(d, pack):
                    files[fname].append(line)
                    index.append(rec(line.split("|", 1)[0], "rules", fname))
                continue
            if t is None and "results" in d:
                files["tables"].append(table_line(d))
                index.append(rec(d["name"], "table", "tables"))
                continue
            fname, fn = route(d, pack)
            if not fn:
                stats[f"skipped:{t}"] += 1
                continue
            s = d.get("system") or {}
            line = fn(d, s, pack)
            files[fname].append(line)
            stats[f"{game}:{t}"] += 1
            lvl = line.split("|")[1] if "|" in line else t
            index.append(rec(d["name"], lvl, fname))
            lore = clean(g(s, "details", "publicNotes")) if t == "npc" else ""
            if lore:
                files["creature-lore"].append(rec(d["name"], lvl, lab("pack", pack), lore))
        # traits glossary from localization (shared, stored under pf2e)
        pre = "PF2E.TraitDescription"
        for k, v in sorted(LANG.items()) if game == "pf2e" else []:
            if k.startswith(pre):
                nm = re.sub(r"(?<!^)(?=[A-Z])", " ", k[len(pre):]).lower()
                files["traits"].append(rec(nm, "trait", clean(v)))
        out = a.out / game
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.txt"):
            old.unlink()
        for fname, lines in files.items():
            lines.sort(key=str.lower)
            (out / f"{fname}.txt").write_text("\n".join(lines) + "\n")
        index.sort(key=str.lower)
        (out / "index.txt").write_text("\n".join(index) + "\n")
    (a.out / "sources.txt").write_text("\n".join(f"{c}|{t}" for c, t in sorted(TITLES.items())) + "\n")
    (a.out / "VERSION").write_text("".join(f"{t} {asset_url(t)}\n" for t in tags.values()))
    for k, v in sorted(stats.items()):
        print(f"{v:6} {k}")


if __name__ == "__main__":
    main()
