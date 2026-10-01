#!/usr/bin/env python3
"""Turn HERO Designer rules data into the hero skill's grep-friendly reference.

Reads the rules directory written by `ork-hero-extract-rules` (from the
ork-hero-export-renderer package: manifest.json plus one JSON file per HERO
Designer template) and writes skill/hero/data/{5e,6e}/<category>.txt, one record
per line.

  ./extract_hero.py [--rules DIR] [--out DIR]

The rules directory defaults to $ORK_HERO_RULES, then ../ork-hero-export-renderer/rules,
then ./rules. The data is Hero Games' copyrighted material: don't commit or share it.
"""
import argparse
import json
import os
import re
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent

SECTIONS = [
    # section, output file, record kind
    ("CHARACTERISTICS", "characteristics", "characteristic"),
    ("SKILLS", "skills", "skill"),
    ("SKILL_ENHANCERS", "skill-enhancers", "skill enhancer"),
    ("MARTIAL_ARTS", "martial-arts", "maneuver"),
    ("PERKS", "perks", "perk"),
    ("TALENTS", "talents", "talent"),
    ("POWERS", "powers", "power"),
    ("MODIFIERS", "modifiers", "modifier"),
    ("DISADVANTAGES", "disadvantages", "disadvantage"),
]

CHAR_NAMES = {
    "STR": "Strength", "DEX": "Dexterity", "CON": "Constitution", "BODY": "Body",
    "INT": "Intelligence", "EGO": "Ego", "PRE": "Presence", "COM": "Comeliness",
    "PD": "Physical Defense", "ED": "Energy Defense", "SPD": "Speed", "REC": "Recovery",
    "END": "Endurance", "STUN": "Stun", "OCV": "Offensive Combat Value",
    "DCV": "Defensive Combat Value", "OMCV": "Offensive Mental Combat Value",
    "DMCV": "Defensive Mental Combat Value", "RUNNING": "Running", "SWIMMING": "Swimming",
    "LEAPING": "Leaping", "SIZE": "Size",
}

# attribute -> label; values are copied as-is (lowercased when the value is a code word)
LABELS = {
    "ALIAS": "alias", "DURATION": "dur", "TARGET": "tgt", "RANGE": "rng", "USESEND": "end",
    "DEFENSE": "def", "CATEGORY": "cat", "OCV": "ocv", "DCV": "dcv", "PHASE": "phase",
    "EFFECT": "effect", "WEAPONEFFECT": "weapon effect", "DC": "dc", "ACTIVECOST": "active",
    "ADDSTR": "addstr", "KILLING": "killing", "RESISTANT": "resistant", "BASE": "base",
    "STANDARDEFFECTALLOWED": "std effect", "VISIBLE": "visible", "SENSEGROUP": "sense group",
    "SENSECOST": "sense cost", "GROUPCOST": "group cost", "COSTSAVINGS": "savings",
}
# attributes that only drive HERO Designer's UI, or that are folded into other fields
SKIP = {
    "XMLID", "DISPLAY", "BASECOST", "LVLCOST", "LVLVAL", "MINVAL", "MAXVAL", "LEVELSTART",
    "MINCOST", "MAXCOST", "EXCLUSIVE", "SHOWDIALOG", "INPUTLABEL", "OTHERINPUT", "POSITION",
    "INCLUDEINBASE", "SHOWOPTIONINPARENS", "SHOWOPTIONONLY", "DISPLAYINSTRING", "SHOWALIAS",
    "WARNSIGN", "STOPSIGN", "ACTIVE", "ACTIVESELECT", "ISLIMITATION", "MULTIPLIER",
    "DOESDAMAGE", "DOESBODY", "DOESKNOCKBACK", "FAMILIARITYROLL", "FAMILIARITYCOST",
    "LVLMULTIPLIER", "LEVELSLABEL", "REQUIRED", "FIXEDVALUE", "LVLPOWER",
}
CODE = re.compile(r"^[A-Z][A-Z_]+$")


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip().replace("|", "¦")


def name_of(n):
    a = n.get("attributes", {})
    return clean(a.get("DISPLAY") or n.get("text") or a.get("XMLID") or n["id"]).replace("[LVL]", "N")


def num(s):
    try:
        return Fraction(s)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def frac(v, sign=True):
    """Fraction as HERO writes modifier values: +1/2, -1 1/4, +2."""
    neg = v < 0
    v = abs(v)
    whole, part = divmod(v.numerator, v.denominator)
    s = " ".join(x for x in (str(whole) if whole or not part else "", f"{part}/{v.denominator}" if part else "") if x)
    return ("-" if neg else "+" if sign else "") + s


def pts(v):
    return str(v.numerator) if v.denominator == 1 else frac(v, sign=False)


def cost(a, modifier):
    """'B, +C per V' (base B, then C more per V levels), plus level and cost ranges."""
    fmt = (lambda v: frac(v)) if modifier else pts
    base, lc, lv = num(a.get("BASECOST")), num(a.get("LVLCOST")), num(a.get("LVLVAL"))
    out = []
    if a.get("MULTIPLIER") == "Yes" and base:
        out.append("x" + pts(base))
    elif base is not None and (base or not lc):
        out.append(fmt(base))
    if lc:
        out.append(f"{fmt(lc)} per {pts(lv or 1)}" if modifier else f"+{pts(lc)} per {pts(lv or 1)}")
    lo, hi = a.get("MINVAL"), a.get("MAXVAL")
    if lc and (lo not in (None, "0", "-999") or hi not in (None, "999")):
        out.append(f"lvls {lo or '0'}..{hi}" if hi not in (None, "999") else f"lvls {lo}+")
    mn, mx = num(a.get("MINCOST")), num(a.get("MAXCOST"))
    if mn is not None and mx is not None and mn != mx:
        out.append(f"range {fmt(mn)}..{fmt(mx)}")
    elif mn is not None and mx is None and mn != base:
        out.append(f"min {fmt(mn)}")
    if a.get("FIXEDVALUE") == "No":
        out.append("variable")
    return ", ".join(out)


def kids(n, *els):
    return [c for c in n.get("children") or [] if c["element"] in els]


def texts(n, el):
    return [clean(c.get("text")) for c in kids(n, el) if clean(c.get("text"))]


def describe(n):
    return " / ".join(texts(n, "DEFINITION"))


def is_mod(n, modifier):
    return modifier or n["element"] == "MODIFIER"


def inline(n, modifier=False):
    """One nested ADDER/MODIFIER/OPTION/etc. rendered on a single line."""
    a = n.get("attributes", {})
    mod = is_mod(n, modifier)
    s = name_of(n)
    c = cost(a, mod)
    flags = [x for x in (c, "required" if a.get("REQUIRED") == "Yes" else "") if x]
    if flags:
        s += f" ({', '.join(flags)})"
    for el, lab in (("EXCLUDES", "excl"), ("REQUIRES", "req")):
        t = texts(n, el)
        if t:
            s += f" [{lab} {', '.join(t)}]"
    opts = kids(n, "OPTION")
    if opts:
        s += " {" + ", ".join(inline(o, mod) for o in opts) + "}"
    sub = kids(n, "ADDER", "MODIFIER")
    if sub:
        s += " {" + "; ".join(inline(o, mod) for o in sub) + "}"
    d = describe(n)
    if d:
        s += ": " + d
    return s


def kind_of(n, kind):
    el = n["element"]
    if kind == "modifier":
        a = n.get("attributes", {})
        vals = [num(a.get(k)) for k in ("BASECOST", "MINCOST", "MAXCOST")]
        vals += [num(o.get("attributes", {}).get("BASECOST")) for o in kids(n, "OPTION")]
        vals = [v for v in vals if v is not None]
        if a.get("ISLIMITATION") == "Yes" or (vals and max(vals) <= 0 and min(vals) < 0):
            return "limitation"
        if vals and min(vals) >= 0 and max(vals) > 0:
            return "advantage"
        return "modifier"
    if el == "SENSEGROUP":
        return "sense group"
    if el == "SENSE":
        return "sense"
    return kind


def record(n, kind, system, edition):
    a = n.get("attributes", {})
    k = kind_of(n, kind)
    if kind == "disadvantage" and edition == "6e":
        k = "complication"
    name = name_of(n)
    if kind == "characteristic" and name in CHAR_NAMES:
        name = f"{name} ({CHAR_NAMES[name]})"
    f = [name, k, system, "id:" + (a.get("XMLID") or n["id"])]
    t = sorted({x.lower() for x in texts(n, "TYPE")})
    if t:
        f.append("type:" + ", ".join(t))
    c = cost(a, k in ("limitation", "advantage", "modifier"))
    if c and c != "0":
        f.append("cost:" + c)
    for ch in kids(n, "CHARACTERISTIC_CHOICE"):
        rolls = []
        for it in kids(ch, "ITEM"):
            ia = it.get("attributes", {})
            rolls.append(f"{ia.get('CHARACTERISTIC', '?')} {cost(ia, False)}")
        f.append("roll:" + "; ".join(rolls))
    if a.get("FAMILIARITYROLL"):
        f.append(f"fam:{a['FAMILIARITYROLL']}- for {a.get('FAMILIARITYCOST', '?')}")
    dmg = [w for w, key in (("damage", "DOESDAMAGE"), ("body", "DOESBODY"), ("knockback", "DOESKNOCKBACK")) if a.get(key) == "Yes"]
    if dmg:
        f.append("does:" + ", ".join(dmg))
    if a.get("REQUIRED") == "Yes":
        f.append("required:yes")
    for key, v in a.items():
        if key in SKIP or key.endswith("INCREASELEVELS"):
            continue
        if key.endswith("INCREASE") and key + "LEVELS" in a:
            f.append(f"figured:+{v} {key[:-8]} per {a[key + 'LEVELS']}")
        elif key.startswith("NCM"):
            f.append(f"{key.lower()}:{v}")
        else:
            f.append(f"{LABELS.get(key, key.lower())}:{v.lower() if CODE.match(v) or v in ('Yes', 'No') else clean(v)}")
    for el, lab in (("EXCLUDES", "excl"), ("REQUIRES", "req"), ("PROVIDES", "provides"), ("SOURCE", "src")):
        t = texts(n, el)
        if t:
            f.append(f"{lab}:{', '.join(dict.fromkeys(t))}")
    mod = k in ("limitation", "advantage", "modifier")
    for el, lab in (("OPTION", "opt"), ("ADDER", "adders"), ("MODIFIER", "mods")):
        ch = kids(n, el)
        if ch:
            f.append(f"{lab}:" + "; ".join(inline(x, mod or el == "MODIFIER") for x in ch))
    other = kids(n, "ENDURANCERESERVEREC", "GROUPS", "PEOPLE", "PLACES", "THINGS")
    for x in other:
        ex = "; ".join(exlist(x))
        f.append(f"{x['element'].lower()}:{inline(x)}" + (f" e.g. {ex}" if ex else ""))
    ex = exlist(n)
    if ex:
        f.append("ex:" + "; ".join(ex))
    if kids(n, "LANGUAGE"):
        f.append(f"languages:{len(kids(n, 'LANGUAGE'))} listed in the languages file")
    f.append(describe(n))
    return "|".join(x for x in f if x)


def exlist(n):
    out = []
    for e in kids(n, "EXAMPLE"):
        t = clean(e.get("text"))
        src = texts(e, "SOURCE")
        out.append(t + (f" ({src[0]})" if src else ""))
    return [x for x in out if x]


def languages(skills, system):
    out = []
    for sk in skills:
        langs = kids(sk, "LANGUAGE")
        disp = {name_of(l).upper(): name_of(l) for l in langs}
        for l in langs:
            f = [name_of(l), "language", system]
            fam = l.get("attributes", {}).get("TYPE")
            if fam:
                f.append("family:" + clean(fam))
            for el, lab in (("FOURPOINTSIMILARITY", "4pt"), ("THREEPOINTSIMILARITY", "3pt"),
                            ("TWOPOINTSIMILARITY", "2pt"), ("ONEPOINTSIMILARITY", "1pt")):
                t = texts(l, el)
                if t:
                    f.append(f"{lab}:" + ", ".join(disp.get(x.upper(), x.title()) for x in t))
            out.append("|".join(f))
    return out


def merge_key(n):
    return (n["element"], n["id"])


def override(base, over):
    o = dict(over)
    o["attributes"] = dict(base.get("attributes", {}), **over.get("attributes", {}))
    if "children" not in over and "children" in base:
        o["children"] = base["children"]
    if "text" not in over and "text" in base:
        o["text"] = base["text"]
    return o


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", help="rules directory written by ork-hero-extract-rules")
    ap.add_argument("--out", default=str(HERE / "skill" / "hero" / "data"), help="output directory")
    a = ap.parse_args()
    cands = [a.rules] if a.rules else [os.environ.get("ORK_HERO_RULES"), str(HERE.parent / "ork-hero-export-renderer" / "rules"), "rules"]
    rules = next((Path(c) for c in cands if c and (Path(c) / "manifest.json").is_file()), None)
    if rules is None:
        sys.exit("no rules directory found (looked for manifest.json in: " + ", ".join(c for c in cands if c) +
                 "); run `npx ork-hero-extract-rules /path/to/HD6.jar` or pass --rules")
    manifest = json.loads((rules / "manifest.json").read_text())
    tpls = {t["id"]: json.loads((rules / (t["id"] + ".json")).read_text()) for t in manifest["templates"]}
    meta = {t["id"]: t for t in manifest["templates"]}
    out = Path(a.out)
    total = 0
    for edition in ("5e", "6e"):
        root = "Main6E" if edition == "6e" else "Main"
        files = {fname: [] for _, fname, _ in SECTIONS}
        files["languages"], files["systems"] = [], []
        base = tpls[root]["sections"]
        main_lines = {}
        for sec, fname, kind in SECTIONS:
            for n in base[sec]["entries"]:
                if n["element"] == "SOURCE":
                    continue
                line = record(n, kind, root, edition)
                main_lines[(sec,) + merge_key(n)] = line
                files[fname].append(line)
        files["languages"] += languages(kids({"children": base["SKILLS"]["entries"]}, "LANGUAGES"), root)
        overlays = sorted(i for i, t in meta.items() if t.get("extends") == root)
        for tid in [root] + overlays:
            t = tpls[tid]
            secs = t["sections"]
            label = clean(next((x.get("text") for x in secs["MAINAPP"]["entries"] if x["id"] == "NAME1" and x.get("text")), ""))
            f = [tid, "system", tid]
            if t.get("extends"):
                f.append("extends:" + t["extends"])
            if label:
                f.append("sheet:" + label)
            attrs = dict(base["MAINAPP"].get("attributes", {}), **secs["MAINAPP"].get("attributes", {}))
            if attrs:
                f.append("settings:" + ", ".join(f"{k.lower()}={v}" for k, v in attrs.items()))
            rem = ["%s %s" % (s.lower(), ", ".join(v)) for s, v in (t.get("removals") or {}).items() if v]
            if rem:
                f.append("removes:" + "; ".join(rem))
            for n in secs["MAINAPP"]["entries"]:
                if n["id"] == "NCM":
                    f.append("ncm:" + inline(n))
            changed = []
            if tid != root:
                for sec, fname, kind in SECTIONS:
                    pidx = {merge_key(n): n for n in base[sec]["entries"]}
                    for n in secs.get(sec, {}).get("entries", []):
                        if n["element"] == "SOURCE":  # a stray <SOURCE> in Normal.hdt's MODIFIERS
                            continue
                        k = merge_key(n)
                        node = override(pidx[k], n) if k in pidx else n
                        line = record(node, kind, tid, edition)
                        if line.split("|", 3)[3:] == main_lines.get((sec,) + k, "").split("|", 3)[3:]:
                            continue
                        files[fname].append(line)
                        changed.append(f"{'changes' if k in pidx else 'adds'} {fname} {name_of(node)}")
            if changed:
                f.append("entries:" + "; ".join(changed))
            files["systems"].append("|".join(f))
        d = out / edition
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.txt"):
            old.unlink()
        index = []
        for fname, lines in files.items():
            (d / (fname + ".txt")).write_text("".join(l + "\n" for l in lines))
            index += ["%s|%s %s|%s" % (p[0], p[1], p[2], fname) for p in (l.split("|", 3) for l in lines)]
            total += len(lines)
            print(f"{edition}/{fname}.txt: {len(lines)} records")
        (d / "index.txt").write_text("".join(l + "\n" for l in index))
    (out / "VERSION").write_text(
        f"HERO Designer {manifest.get('appVersion', '?')} ({manifest.get('sourceJar', '?')}), "
        f"rules extracted {manifest.get('extractedAt', '?')}\n")
    print(f"{total} records -> {out}")


if __name__ == "__main__":
    main()
