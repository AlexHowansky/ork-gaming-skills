#!/usr/bin/env python3
"""Extract the D&D 5e SRD (2014 SRD 5.1 and 2024 SRD 5.2) from the foundryvtt/dnd5e system release zip into
compact, grep-friendly text files: one record per line, pipe-delimited, labeled fields. Only the compendium packs
are fetched from the zip (with HTTP range requests); the system's inline roll enrichers are rendered to plain
text, computing monster attack bonuses, damage and save DCs the way Foundry does."""
import argparse
import html
import io
import json
import math
import re
import struct
import sys
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict

REPO = "foundryvtt/dnd5e"
UA = {"User-Agent": "ork-gaming-skills-extract"}

# pack -> edition; packs not listed (heroes = pregens, effects = active effects) are skipped
EDITIONS = {
    "spells": "2014", "items": "2014", "tradegoods": "2014", "classes": "2014", "subclasses": "2014",
    "classfeatures": "2014", "races": "2014", "backgrounds": "2014", "monsters": "2014", "monsterfeatures": "2014",
    "rules": "2014", "tables": "2014",
    "spells24": "2024", "equipment24": "2024", "classes24": "2024", "origins24": "2024", "feats24": "2024",
    "actors24": "2024", "monsterfeatures24": "2024", "content24": "2024", "tables24": "2024",
}

DOCS: Dict[str, dict] = {}       # document id -> document (items, actors, journals, pages, tables)
PACK_DOCS: Dict[tuple, dict] = {}  # (pack, id) -> document; ids are only unique within a pack
EMBEDDED: Dict[tuple, list] = {}  # (pack, actor id) -> embedded items
RULE_NAMES: Dict[str, str] = {}  # slug -> rule page name, for &Reference[...]
SCALES: Dict[tuple, dict] = {}   # (edition, "<class>.<scale>") -> ScaleValue advancement
EDITION = ["2024"]               # edition of the pack being formatted (class identifiers repeat across editions)
GRANTED = {}                     # item id -> "Class N" (level it is granted at)


def asset_name(tag: str) -> str:
    return f"dnd5e-{tag}.zip"


def asset_url(tag: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{tag}/{asset_name(tag)}"


def fetch(url: str, headers=None) -> bytes:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **(headers or {})}), timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"error: {url}: HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"error: {url}: {e.reason}")


def latest_tag() -> str:
    """Newest non-draft, non-prerelease tag that has a dnd5e-release-*.zip."""
    for r in json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases?per_page=20")):
        if not r.get("draft") and not r.get("prerelease") and any(
                x["name"] == asset_name(r["tag_name"]) for x in r.get("assets", [])):
            return r["tag_name"]
    sys.exit("error: no release with a dnd5e-release zip found")


class HttpRangeFile(io.RawIOBase):
    """Read-only, seekable view of a remote file that fetches only the byte ranges it is asked for."""

    def __init__(self, url):
        req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                if r.status != 206:
                    raise ValueError("server ignored the Range header")
                self.url = r.geturl()  # follow the release-asset redirect once
                self.size = int(r.headers["Content-Range"].rsplit("/", 1)[1])
        except urllib.error.HTTPError as e:
            sys.exit(f"error: {url}: HTTP {e.code} {e.reason}")
        except urllib.error.URLError as e:
            sys.exit(f"error: {url}: {e.reason}")
        self.pos = 0
        self.fetched = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        end = self.size if n is None or n < 0 else min(self.size, self.pos + n)
        if end <= self.pos:
            return b""
        data = fetch(self.url, {"Range": f"bytes={self.pos}-{end - 1}"})
        self.fetched += len(data)
        self.pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def open_packs(tag: str) -> Dict[str, bytes]:
    """packs/* members of the release zip, keyed by name. Uses range requests so the ~100 MB of token art is never
    downloaded; falls back to the whole zip if the server doesn't support ranges. Nothing is written to disk."""
    url = asset_url(tag)
    try:
        f = HttpRangeFile(url)
        zf = zipfile.ZipFile(io.BufferedReader(f, buffer_size=1 << 16))
    except ValueError:
        f = None
        zf = zipfile.ZipFile(io.BytesIO(fetch(url)))
    out = {}
    for info in zf.infolist():
        if info.filename.startswith("packs/") and not info.is_dir():
            out[info.filename] = zf.read(info)
    got = f.fetched if f else sum(i.compress_size for i in zf.infolist())
    print(f"{tag}: {got / 1e6:.1f} MB fetched", file=sys.stderr)
    return out


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


def read_pack(files: Dict[str, bytes], pack: str) -> Dict[str, dict]:
    """All live documents in packs/<pack>/, keyed by LevelDB key (e.g. '!items!<id>')."""
    best = {}
    for name, data in files.items():
        m = re.fullmatch(rf"packs/{re.escape(pack)}/[^/]+\.(ldb|log)", name)
        if not m:
            continue
        for key, seq, kind, v in (sstable(data) if m.group(1) == "ldb" else wal(data)):
            if key not in best or seq > best[key][0]:
                best[key] = (seq, kind, v)
    return {k.decode(): json.loads(v) for k, (_, kind, v) in sorted(best.items()) if kind == 1}


def packs(files: Dict[str, bytes]):
    return sorted({m.group(1) for n in files for m in [re.match(r"packs/([^/]+)/", n)] if m})


# ---------------------------------------------------------------- config tables (from dnd5e module/config.mjs)

ABILITIES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution", "int": "Intelligence", "wis": "Wisdom",
             "cha": "Charisma"}
SKILLS = {"acr": ("Acrobatics", "dex"), "ani": ("Animal Handling", "wis"), "arc": ("Arcana", "int"),
          "ath": ("Athletics", "str"), "dec": ("Deception", "cha"), "his": ("History", "int"),
          "ins": ("Insight", "wis"), "itm": ("Intimidation", "cha"), "inv": ("Investigation", "int"),
          "med": ("Medicine", "wis"), "nat": ("Nature", "int"), "prc": ("Perception", "wis"),
          "prf": ("Performance", "cha"), "per": ("Persuasion", "cha"), "rel": ("Religion", "int"),
          "slt": ("Sleight of Hand", "dex"), "ste": ("Stealth", "dex"), "sur": ("Survival", "wis")}
SKILL_SLUG = {re.sub(r"[^a-z]", "", v[0].lower()): k for k, v in SKILLS.items()}
TOOLS = {"alchemist": "Alchemist's Supplies", "brewer": "Brewer's Supplies", "calligrapher": "Calligrapher's Supplies",
         "carpenter": "Carpenter's Tools", "cartographer": "Cartographer's Tools", "cobbler": "Cobbler's Tools",
         "cook": "Cook's Utensils", "glassblower": "Glassblower's Tools", "jeweler": "Jeweler's Tools",
         "leatherworker": "Leatherworker's Tools", "mason": "Mason's Tools", "painter": "Painter's Supplies",
         "potter": "Potter's Tools", "smith": "Smith's Tools", "tinker": "Tinker's Tools",
         "weaver": "Weaver's Tools", "woodcarver": "Woodcarver's Tools", "disg": "Disguise Kit",
         "forg": "Forgery Kit", "herb": "Herbalism Kit", "navg": "Navigator's Tools", "pois": "Poisoner's Kit",
         "thief": "Thieves' Tools"}
DAMAGE_TYPES = {k: k.capitalize() for k in ("acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic",
                                            "piercing", "poison", "psychic", "radiant", "slashing", "thunder")}
HEALING_TYPES = {"healing": "Hit Points", "temphp": "Temporary Hit Points", "maximum": "Maximum Hit Points"}
SCHOOLS = {"abj": "Abjuration", "con": "Conjuration", "div": "Divination", "enc": "Enchantment", "evo": "Evocation",
           "ill": "Illusion", "nec": "Necromancy", "trs": "Transmutation"}
SIZES = {"tiny": "Tiny", "sm": "Small", "med": "Medium", "lg": "Large", "huge": "Huge", "grg": "Gargantuan"}
CREATURE_TYPES = {k: k.capitalize() for k in ("aberration", "beast", "celestial", "construct", "dragon", "elemental",
                                              "fey", "fiend", "giant", "humanoid", "monstrosity", "ooze", "plant",
                                              "undead")}
CREATURE_PLURAL = {"monstrosity": "Monstrosities", "fey": "Fey", "undead": "Undead"}
ITEM_PROPERTIES = {"ada": "Adamantine", "amm": "Ammunition", "concentration": "Concentration", "fin": "Finesse",
                   "fir": "Firearm", "foc": "Focus", "hvy": "Heavy", "lgt": "Light", "lod": "Loading",
                   "material": "Material", "mgc": "Magical", "rch": "Reach", "rel": "Reload", "ret": "Returning",
                   "ritual": "Ritual", "sil": "Silvered", "somatic": "Somatic", "spc": "Special",
                   "stealthDisadvantage": "Stealth Disadvantage", "thr": "Thrown", "two": "Two-Handed",
                   "ver": "Versatile", "vocal": "Verbal"}
WEAPON_TYPES = {"simpleM": "Simple Melee", "simpleR": "Simple Ranged", "martialM": "Martial Melee",
                "martialR": "Martial Ranged", "natural": "Natural", "improv": "Improvised", "siege": "Siege Weapon"}
WEAPON_ATTACK = {"simpleM": "melee", "simpleR": "ranged", "martialM": "melee", "martialR": "ranged", "siege": "ranged"}
ARMOR_TYPES = {"light": "Light Armor", "medium": "Medium Armor", "heavy": "Heavy Armor", "natural": "Natural Armor",
               "shield": "Shield"}
EQUIP_TYPES = {**ARMOR_TYPES, "clothing": "Clothing", "ring": "Ring", "rod": "Rod", "trinket": "Trinket",
               "vehicle": "Vehicle Equipment", "wand": "Wand", "wondrous": "Wondrous Item"}
CONSUMABLE_TYPES = {"ammo": "Ammunition", "potion": "Potion", "poison": "Poison", "food": "Food", "scroll": "Scroll",
                    "wand": "Wand", "rod": "Rod", "trinket": "Trinket", "wondrous": "Wondrous Item"}
TOOL_TYPES = {"art": "Artisan's Tools", "game": "Gaming Set", "music": "Musical Instrument"}
LOOT_TYPES = {"art": "Art Object", "gear": "Adventuring Gear", "gem": "Gemstone", "junk": "Junk",
              "material": "Material", "resource": "Resource", "trade": "Trade Good", "treasure": "Treasure"}
RARITY = {"common": "Common", "uncommon": "Uncommon", "rare": "Rare", "veryRare": "Very Rare",
          "legendary": "Legendary", "artifact": "Artifact"}
ACTIVATION = {"action": "Action", "bonus": "Bonus Action", "reaction": "Reaction", "minute": "Minute",
              "hour": "Hour", "day": "Day", "longRest": "End of a Long Rest", "shortRest": "End of a Short Rest",
              "encounter": "Start of Encounter", "turnStart": "Start of Turn", "turnEnd": "End of Turn",
              "legendary": "Legendary Action", "mythic": "Mythic Action", "lair": "Lair Action",
              "crew": "Crew Action", "special": "Special"}
TIME_UNITS = {"turn": "turn", "round": "round", "second": "second", "minute": "minute", "hour": "hour", "day": "day",
              "week": "week", "month": "month", "year": "year"}
TIME_SPECIAL = {"inst": "Instantaneous", "spec": "Special", "disp": "Until Dispelled",
                "dstr": "Until Dispelled or Triggered", "perm": "Permanent"}
RANGE_SPECIAL = {"self": "Self", "touch": "Touch", "spec": "Special", "any": "Any"}
UNITS = {"ft": ("ft", "foot", "feet"), "mi": ("mi", "mile", "miles"), "m": ("m", "meter", "meters"),
         "km": ("km", "kilometer", "kilometers")}
PERIODS = {"lr": "Long Rest", "sr": "Short Rest", "day": "Day", "dawn": "Dawn", "dusk": "Dusk",
           "initiative": "Initiative", "turnStart": "Start of Turn", "turnEnd": "End of Turn", "turn": "Each Turn"}
FEATURE_TYPES = {"background": "Background Feature", "class": "Class Feature", "monster": "Monster Feature",
                 "race": "Species Feature", "feat": "Feat", "supernaturalGift": "Supernatural Gift",
                 "vehicle": "Vehicle Feature"}
FEAT_SUBTYPES = {"origin": "Origin", "general": "General", "fightingStyle": "Fighting Style", "epicBoon": "Epic Boon",
                 "channelDivinity": "Channel Divinity", "eldritchInvocation": "Eldritch Invocation", "ki": "Ki",
                 "metamagic": "Metamagic", "pact": "Pact Boon", "defensiveTactic": "Defensive Tactic",
                 "huntersPrey": "Hunter's Prey", "superiorHuntersDefense": "Superior Hunter's Defense",
                 "multiattack": "Multiattack", "maneuver": "Maneuver", "arcaneShot": "Arcane Shot",
                 "artificerInfusion": "Artificer Infusion", "elementalDiscipline": "Elemental Discipline",
                 "rune": "Rune"}
MOVEMENT = {"walk": "Speed", "burrow": "Burrow", "climb": "Climb", "fly": "Fly", "swim": "Swim"}
SENSES = {"blindsight": "Blindsight", "darkvision": "Darkvision", "tremorsense": "Tremorsense",
          "truesight": "Truesight"}
LANGUAGES = {"common": "Common", "dwarvish": "Dwarvish", "elvish": "Elvish", "giant": "Giant", "gnomish": "Gnomish",
             "goblin": "Goblin", "halfling": "Halfling", "orc": "Orc", "sign": "Common Sign Language",
             "draconic": "Draconic", "aarakocra": "Aarakocra", "abyssal": "Abyssal", "celestial": "Celestial",
             "deep": "Deep Speech", "gith": "Gith", "gnoll": "Gnoll", "infernal": "Infernal", "primordial": "Primordial",
             "aquan": "Aquan", "auran": "Auran", "ignan": "Ignan", "terran": "Terran", "sylvan": "Sylvan",
             "undercommon": "Undercommon", "cant": "Thieves' Cant", "druidic": "Druidic"}
AREA = {  # template type -> (label, dimensions)
    "circle": ("Circle", ["radius"]), "cone": ("Cone", ["length"]), "cube": ("Cube", ["width"]),
    "cylinder": ("Cylinder", ["radius", "height"]), "line": ("Line", ["length", "width"]),
    "radius": ("Emanation", []), "ring": ("Ring", ["radius", "thickness", "height"]),
    "sphere": ("Sphere", ["radius"]), "square": ("Square", ["width"]), "wall": ("Wall", ["length", "thickness", "height"])}
DIM_WORD = {"radius": "radius", "length": "long", "width": "wide", "height": "high", "thickness": "thick"}
TARGETS = {  # affects type -> (singular, plural)
    "ally": ("ally", "allies"), "enemy": ("enemy", "enemies"), "creature": ("creature", "creatures"),
    "object": ("object", "objects"), "space": ("space", "spaces"),
    "creatureOrObject": ("creature or object", "creatures or objects"), "any": ("target", "targets"),
    "willing": ("willing creature", "willing creatures"), "": ("target", "targets")}
CR_XP = [10, 200, 450, 700, 1100, 1800, 2300, 2900, 3900, 5000, 5900, 7200, 8400, 10000, 11500, 13000, 15000, 18000,
         20000, 22000, 25000, 33000, 41000, 50000, 62000, 75000, 90000, 105000, 120000, 135000, 155000]
WORDS = "zero one two three four five six seven eight nine ten".split()
CURRENCY = {"pp": "pp", "gp": "gp", "ep": "ep", "sp": "sp", "cp": "cp"}


def words(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def fmt_num(n):
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return f"{n:,}" if isinstance(n, int) else str(n)


def signed(n):
    return f"+{n}" if n >= 0 else f"−{-n}".replace("−", "-")


def slug(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def cap(s):
    return s[:1].upper() + s[1:] if s else s


def or_list(items):
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1] if items else ""


def and_list(items):
    items = [i for i in items if i]
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def length(v, units="ft"):
    if v in (None, ""):
        return ""
    return f"{fmt_num(v)} {UNITS.get(units or 'ft', (units,))[0]}"


def g(o, *keys, default=None):
    for k in keys:
        if not isinstance(o, dict):
            return default
        o = o.get(k)
    return default if o is None else o


def cr_text(cr):
    return {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}.get(cr, fmt_num(cr) if cr is not None else "")


def cr_xp(cr):
    if cr is None:
        return 0
    if cr < 1:
        return {0: 10, 0.125: 25, 0.25: 50, 0.5: 100}.get(cr, 0)
    return CR_XP[min(int(cr), 30)]


# ---------------------------------------------------------------- dice and formulas

def lookup_path(data, path):
    for k in path.split("."):
        if isinstance(data, dict) and k in data:
            data = data[k]
        else:
            return None
    return data


def substitute(formula, data):
    """Replace @paths in a formula with values from `data` (None if one is missing)."""
    missing = []

    def rep(m):
        v = lookup_path(data, m.group(1))
        if isinstance(v, dict):
            v = v.get("value", v.get("formula"))
        if v in (None, "") or isinstance(v, (dict, list)):
            missing.append(m.group(1))
            return "0"
        return f"({v})" if isinstance(v, str) and re.search(r"[+\-*/ ]", v.strip()) else str(v)

    out = re.sub(r"@([\w.\-]+)", rep, str(formula))
    return None if missing else out


def evaluate(expr):
    """Evaluate a deterministic arithmetic formula (with floor/ceil/min/max/round), or None."""
    if expr is None:
        return None
    e = str(expr).strip()
    if not e or not re.fullmatch(r"[\d+\-*/(). ,]*", re.sub(r"\b(floor|ceil|min|max|round)\(", "(", e)):
        return None
    try:
        v = eval(e, {"__builtins__": {}}, {"floor": math.floor, "ceil": math.ceil, "min": min, "max": max,
                                           "round": round})
    except Exception:
        return None
    return int(v) if isinstance(v, float) and v.is_integer() else v


def simplify(formula, data=None):
    """Substitute and combine constants: '1d10 + @mod' -> '1d10 + 8'. Returns (text, average or None)."""
    f = substitute(formula, data or {}) if "@" in str(formula) else str(formula)
    if f is None:
        return str(formula), None
    f = f.replace(" ", "")
    # fold parenthesized arithmetic
    while True:
        m = re.search(r"\(([\d+\-*/]+)\)", f)
        if not m:
            break
        v = evaluate(m.group(1))
        if v is None:
            break
        f = f[:m.start()] + str(v) + f[m.end():]
    terms = re.findall(r"([+\-]?)([^+\-]+)", f)
    dice, const, other = [], 0, []
    for sign, t in terms:
        if not t:
            continue
        m = re.fullmatch(r"(\d*)d(\d+)", t)
        if m:
            dice.append((sign or "+", int(m.group(1) or 1), int(m.group(2))))
            continue
        v = evaluate(t)
        if isinstance(v, (int, float)):
            const += -v if sign == "-" else v
        else:
            other.append(sign + t)
    if other:
        return re.sub(r"([+\-])", r" \1 ", f).strip().lstrip("+ ").strip(), None
    parts = []
    for i, (sign, n, d) in enumerate(dice):
        parts.append(("" if i == 0 and sign == "+" else f" {sign} ") + f"{n}d{d}")
    if const or not parts:
        c = int(const) if float(const).is_integer() else const
        parts.append(str(c) if not parts else f" {'+' if c >= 0 else '-'} {abs(c)}")
    lo = sum((n if s == "+" else -n * d) for s, n, d in dice) + const
    hi = sum((n * d if s == "+" else -n) for s, n, d in dice) + const
    return "".join(parts), math.floor((lo + hi) / 2)


def humanize(formula):
    """Words for the roll-data references in a formula shown without an actor:
    'max(1, @abilities.cha.mod)' -> 'Charisma modifier (min 1)'."""
    f = str(formula)
    if "@" not in f:
        return f

    def ref(m):
        p = m.group(1)
        if p.startswith("scale."):
            adv = SCALES.get((EDITION[0], p.split(".", 1)[1]))
            return adv.get("title") if adv else p.split(".")[-1]
        m2 = re.fullmatch(r"abilities\.(\w+)\.(mod|value|dc)", p)
        if m2:
            return f"{ABILITIES.get(m2.group(1), m2.group(1))} {'modifier' if m2.group(2) == 'mod' else m2.group(2)}"
        m2 = re.fullmatch(r"classes\.([\w-]+)\.levels", p)
        if m2:
            return f"{m2.group(1).replace('-', ' ').title()} level"
        return {"prof": "Proficiency Bonus", "mod": "modifier", "item.level": "spell level",
                "details.level": "character level", "attributes.prof": "Proficiency Bonus",
                "attributes.spell.dc": "spell save DC", "details.cr": "CR"}.get(p, p.split(".")[-1])

    f = re.sub(r"@([\w.\-]+)", ref, f)
    f = re.sub(r"max\(\s*(\d+)\s*,\s*([^()]+)\)", r"\2 (min \1)", f)
    f = re.sub(r"(floor|ceil)\(([^()]+)\)", lambda m: f"{m.group(2)} (round {'down' if m.group(1) == 'floor' else 'up'})", f)
    return f


def damage_formula(part):
    """Formula of a DamageField: custom formula, or NdM + bonus."""
    if g(part, "custom", "enabled") and g(part, "custom", "formula"):
        return str(part["custom"]["formula"])
    if not part.get("denomination"):
        return str(part.get("bonus") or "")
    f = f"{part.get('number') or 1}d{part['denomination']}"
    if part.get("bonus"):
        b = str(part["bonus"]).strip()
        f += b if b.startswith(("+", "-")) else f" + {b}"
    return f


# ---------------------------------------------------------------- actors (derived NPC statistics)

def advancements(d):
    adv = g(d, "system", "advancement", default=[]) or []
    return [a for a in (adv.values() if isinstance(adv, dict) else adv) if isinstance(a, dict)]


def sorted_activities(item):
    acts = g(item, "system", "activities", default={}) or {}
    return sorted(acts.values(), key=lambda a: a.get("sort") or 0) if isinstance(acts, dict) else []


def derive(actor):
    """The computed statistics Foundry derives for an NPC: modifiers, proficiency, saves, skills, DCs, AC."""
    s = actor.get("system") or {}
    rules = g(s, "source", "rules") or "2014"
    cr = g(s, "details", "cr")
    prof = 2 + (max(cr or 0, 1) - 1) // 4 if actor.get("type") == "npc" else 2
    prof = int(prof)
    ab = {}
    for k in ABILITIES:
        a = g(s, "abilities", k, default={})
        v = a.get("value") or 10
        mod = (v - 10) // 2
        mult = a.get("proficient") or 0
        bonus = evaluate(substitute(g(a, "bonuses", "save") or "0", {"prof": prof})) or 0
        ab[k] = {"value": v, "mod": mod, "proficient": mult, "save": mod + math.floor(mult * prof) + bonus,
                 "dc": 8 + mod + prof}
    data = {"abilities": ab, "prof": prof, "attributes": {"prof": prof}}
    sk = {}
    for k, (label, abil) in SKILLS.items():
        sd = g(s, "skills", k, default={})
        a = sd.get("ability") or abil
        mult = sd.get("value") or 0
        bonus = evaluate(substitute(g(sd, "bonuses", "check") or "0", data)) or 0
        total = ab[a]["mod"] + math.floor(mult * prof) + bonus
        pbonus = evaluate(substitute(g(sd, "bonuses", "passive") or "0", data)) or 0
        sk[k] = {"value": mult, "total": total, "mod": total, "passive": 10 + total + pbonus}
    spell_ability = g(s, "attributes", "spellcasting") or ""
    spell_dc = ab[spell_ability]["dc"] if spell_ability in ab else 8 + prof
    init_bonus = evaluate(substitute(g(s, "attributes", "init", "bonus") or "0", data)) or 0
    init = ab["dex"]["mod"] + init_bonus
    items = EMBEDDED.get((actor.get("_pack"), actor["_id"]), [])
    legact = g(s, "resources", "legact", "max") or 0
    lair = g(s, "resources", "lair", "value")
    name = actor["name"]
    if legact:
        if rules == "2014":
            n = f"{legact} legendary action{'s' if legact != 1 else ''}"
            leg_desc = (f"The {name.lower()} can take {n}, choosing from the options below. Only one legendary "
                        f"action option can be used at a time and only at the end of another creature’s turn. The "
                        f"{name.lower()} regains spent legendary actions at the start of its turn.")
        else:
            uses = f"{legact} ({legact + 1} in Lair)" if lair else str(legact)
            leg_desc = (f"Legendary Action Uses: {uses}. Immediately after another creature’s turn, the "
                        f"{name.lower()} can expend a use to take one of the following actions. The {name.lower()} "
                        f"regains all expended uses at the start of each of its turns.")
    else:
        leg_desc = ""
    t = g(s, "details", "type", default={}) or {}
    rd = {
        "name": name, "prof": prof, "abilities": ab, "skills": sk,
        "attributes": {"prof": prof, "spell": {"dc": spell_dc, "level": g(s, "attributes", "spell", "level")},
                       "spelldc": spell_dc, "init": {"total": init},
                       "hp": g(s, "attributes", "hp", default={}), "spellcasting": spell_ability},
        "details": {**(s.get("details") or {}),
                    "type": {**t, "config": {"label": CREATURE_TYPES.get(t.get("value"), t.get("custom") or "")}}},
        "resources": {"legact": {"max": legact, "label": leg_desc}, "legres": g(s, "resources", "legres")},
    }
    return {"actor": actor, "rules": rules, "prof": prof, "abilities": ab, "skills": sk, "cr": cr,
            "spell_ability": spell_ability, "spell_dc": spell_dc, "init": init, "items": items, "rolldata": rd,
            "legendary": leg_desc}


def armor_class(A):
    """AC value and its 2014-style label, like Foundry's prepareArmorClass."""
    s = A["actor"]["system"]
    ac = g(s, "attributes", "ac", default={})
    calc = ac.get("calc") or "default"
    mods = {k: v["mod"] for k, v in A["abilities"].items()}
    if calc == "flat":
        return ac.get("flat") or 10, ""
    if calc == "natural":
        return ac.get("flat") or 10, "Natural Armor"
    armors = [i for i in A["items"] if i["type"] == "equipment" and g(i, "system", "equipped")
              and g(i, "system", "type", "value") in ARMOR_TYPES]
    armor = next((i for i in armors if g(i, "system", "type", "value") != "shield"), None)
    shield = next((i for i in armors if g(i, "system", "type", "value") == "shield"), None)
    best, label = -1, ""
    if armor:
        dexcap = g(armor, "system", "armor", "dex")
        heavy = g(armor, "system", "type", "value") == "heavy"
        dex = 0 if heavy else min(mods["dex"], dexcap if dexcap is not None else 99)
        best, label = (g(armor, "system", "armor", "value") or 10) + dex, armor["name"]
    else:
        formulas = {"unarmored": 10 + mods["dex"], "mage": 13 + mods["dex"], "draconic": 13 + mods["dex"],
                    "unarmoredMonk": 10 + mods["dex"] + mods["wis"], "unarmoredBarb": 10 + mods["dex"] + mods["con"]}
        best = formulas["unarmored"]
        if calc in formulas and formulas[calc] > best:
            best, label = formulas[calc], {"mage": "Mage Armor", "draconic": "Draconic Resilience"}.get(calc, "")
        if calc == "custom" and ac.get("formula"):
            v = evaluate(substitute(ac["formula"], A["rolldata"]))
            if v is not None:
                best = v
    if shield:
        best += g(shield, "system", "armor", "value") or 2
        label = ", ".join(x for x in (label, shield["name"]) if x)
    best += evaluate(substitute(ac.get("bonus") or "0", A["rolldata"])) or 0
    return best, label


# ---------------------------------------------------------------- activities

def act_field(item, act, field):
    """An activity's range/target/duration/activation, falling back to the item's unless overridden."""
    a = act.get(field) if act else None
    if a and a.get("override"):
        return a
    item_v = g(item, "system", field)
    if isinstance(item_v, dict) and item_v:
        return item_v
    return a or {}


def range_label(rng, long=False):
    units = rng.get("units")
    if not units:
        return "Self"
    if units in RANGE_SPECIAL:
        return RANGE_SPECIAL[units]
    v = rng.get("value")
    if not v:
        return ""
    return f"{fmt_num(v)} {UNITS.get(units, (units, units, units))[2 if long else 0]}"


def area_label(tpl):
    """'20-foot-radius Sphere'."""
    t = tpl.get("type")
    if t not in AREA:
        return ""
    label, dims = AREA[t]
    unit = UNITS.get(tpl.get("units") or "ft", ("", "foot"))[1]
    size_word = (dims or ["size"])[0]
    sizes = [f"{tpl.get('size')}-{unit}" + (f"-{DIM_WORD[size_word]}" if size_word == "radius" or len(dims) > 1
                                              else "")] if tpl.get("size") else []
    for d in dims[1:]:
        if d in ("width", "height", "thickness"):
            v = tpl.get("width" if d == "thickness" else d) or "5"
            sizes.append(f"{v}-{unit}-{DIM_WORD[d]}")
    count = int(tpl.get("count") or 1) if str(tpl.get("count") or "1").isdigit() else 1
    sized = ", ".join(sizes)
    return f"{sized} {label}".strip() if count == 1 else f"{words(count)} {sized} {label}s"


def affects_labels(target):
    aff = target.get("affects") or {}
    tpl = target.get("template") or {}
    t = aff.get("type") or ""
    special = aff.get("special") or ""
    one, other = TARGETS.get(t, ("target", "targets"))
    if special:
        one = other = special
    count = aff.get("count")
    if count not in (None, ""):
        n = int(count) if str(count).isdigit() else count
        desc = f"{words(n)} {one if n == 1 else other}"
    else:
        desc = f"{'each' if tpl.get('type') else 'any'} {one if tpl.get('type') else other}"
    n = int(count) if str(count or "").isdigit() else 1
    statblock = f"{words(n)} {TARGETS.get(t, ('target', 'targets'))[0 if n == 1 else 1]}"
    return desc, statblock


def duration_label(dur):
    u = dur.get("units") or ""
    if u in TIME_SPECIAL:
        return dur.get("special") or TIME_SPECIAL[u] if u == "spec" else TIME_SPECIAL[u]
    if u in TIME_UNITS:
        v = dur.get("value") or 1
        n = int(v) if str(v).isdigit() else v
        return f"{n} {TIME_UNITS[u]}{'' if n == 1 else 's'}"
    return ""


def activation_label(act):
    t = act.get("type") or ""
    v = act.get("value")
    lab = ACTIVATION.get(t, t)
    if t in ("minute", "hour", "day") and v:
        return f"{v} {lab}{'s' if str(v) != '1' else ''}"
    if t in ("legendary", "mythic") and v and str(v) != "1":
        return f"{lab} (costs {v})"
    return lab


def activity_rolldata(item, act):
    """`activity.getRollData().activity`: activity data with item fallbacks and computed labels."""
    rng = act_field(item, act, "range")
    target = act_field(item, act, "target")
    dur = act_field(item, act, "duration")
    activation = act_field(item, act, "activation")
    desc_aff, statblock = affects_labels(target)
    tpl = dict(target.get("template") or {})
    if tpl.get("type"):
        tpl.setdefault("count", "1")
    data = dict(act)
    data.update({
        "range": rng, "duration": dur, "activation": activation,
        "target": {**target, "template": tpl,
                   "affects": {**(target.get("affects") or {}), "labels": {"statblock": statblock,
                                                                           "description": desc_aff}}},
        "labels": {"description": {"affects": desc_aff, "template": area_label(tpl),
                                   "range": range_label(rng, long=True)},
                   "duration": duration_label(dur), "activation": activation_label(activation),
                   "range": range_label(rng)},
    })
    return data


# ---------------------------------------------------------------- enrichers

class Ctx:
    """What text is being enriched relative to: an item (maybe on an actor), or a journal page."""

    def __init__(self, item=None, A=None, rules=None, depth=0):
        rules = rules or g(item, "system", "source", "rules") or "2024"
        self.item, self.A, self.rules, self.depth = item, A, str(rules), depth

    def acts(self, types=None):
        return [a for a in sorted_activities(self.item) if not types or a.get("type") in types] if self.item else []

    def act(self, aid):
        if not self.item or not aid:
            return None
        return (g(self.item, "system", "activities", default={}) or {}).get(aid) or next(
            (a for a in self.acts() if a.get("name") == aid), None)

    def rolldata(self):
        """`item.getRollData()`: the actor's roll data plus `item`."""
        d = dict(self.A["rolldata"]) if self.A else {}
        if self.item:
            sysd = dict(self.item.get("system") or {})
            sysd["name"] = self.item["name"]
            if "uses" in sysd and isinstance(sysd["uses"], dict):
                u = dict(sysd["uses"])
                mx = evaluate(substitute(u.get("max") or "", d)) if u.get("max") else None
                u["max"] = mx if mx is not None else u.get("max")
                sysd["uses"] = u
            d["item"] = sysd
            d.setdefault("mod", 0)
        return d


def parse_config(s):
    cfg = {"values": []}
    for part in re.findall(r'(?:[^\s"]+|"[^"]*")+', s or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            cfg[k] = v.strip('"')
        else:
            cfg["values"].append(part.strip('"'))
    return cfg


def ability_key(v):
    v = slug(v)
    for k, lab in ABILITIES.items():
        if v in (k, slug(lab)):
            return k
    return None


def ability_mod(A, key):
    return A["abilities"][key]["mod"] if A and key in A["abilities"] else 0


def attack_ability(ctx, act):
    item = ctx.item
    s = item.get("system") or {}
    atk = act.get("attack") or {}
    choice = atk.get("ability") or ""
    if choice == "none":
        return None
    if choice in ABILITIES:
        return choice
    cls = g(atk, "type", "classification") or ("spell" if item["type"] == "spell" else "weapon")
    if choice == "spellcasting" or cls == "spell" and item["type"] == "spell":
        return ctx.A["spell_ability"] if ctx.A else None
    wtype = g(s, "type", "value")
    if item["type"] == "weapon" and (cls == "weapon" or wtype == "natural"):
        if "fin" in (s.get("properties") or []) or wtype == "natural":
            options = ["str", "dex"]
        elif wtype in WEAPON_ATTACK:
            options = ["str" if WEAPON_ATTACK[wtype] == "melee" else "dex"]
        else:
            options = ["str"]
        return max(options, key=lambda k: ability_mod(ctx.A, k))
    if cls == "spell":
        return ctx.A["spell_ability"] if ctx.A else None
    return "dex" if g(atk, "type", "value") == "ranged" else "str"


def attack_types(item, act):
    if item["type"] == "weapon":
        s = item["system"]
        at = WEAPON_ATTACK.get(g(s, "type", "value"))
        types = []
        if at in ("melee", None):
            types.append("melee")
        if at == "ranged" or "thr" in (s.get("properties") or []) or (at is None and g(s, "range", "value")):
            types.append("ranged")
        return types
    return [g(act, "attack", "type", "value") or "melee"]


def attack_bonus(ctx, act):
    if not ctx.A:
        return None
    atk = act.get("attack") or {}
    rd = ctx.rolldata()
    bonus = evaluate(substitute(atk.get("bonus") or "0", rd)) or 0
    if atk.get("flat"):
        return bonus
    ab = attack_ability(ctx, act)
    magic = evaluate(substitute(str(g(ctx.item, "system", "magicalBonus") or 0), rd)) or 0
    return ability_mod(ctx.A, ab) + ctx.A["prof"] + bonus + magic


def weapon_range_label(item, act, types):
    s = item.get("system") or {}
    if item["type"] != "weapon":
        return range_label(act_field(item, act, "range"))
    parts = []
    rng = s.get("range") or {}
    units = rng.get("units") or "ft"
    if "melee" in types:
        parts.append(f"reach {length(rng.get('reach') or 5, units)}")
    if "ranged" in types:
        ar = act.get("range") or {}
        if ar.get("override") and ar.get("value"):
            r = length(ar["value"], ar.get("units") or units)
        else:
            v, lng = rng.get("value"), rng.get("long")
            r = length(v, units) if not lng or lng == v else f"{fmt_num(v)}/{length(lng, units)}"
        if r:
            parts.append(f"range {r}")
    return or_list(parts)


def enrich_attack(cfg, label, ctx):
    fparts = []
    extended = cfg.get("format") == "extended"
    for v in cfg["values"]:
        if v == "extended":
            extended = True
        elif v not in ("oneHanded", "twoHanded", "offhand", "thrown", "thrown-offhand", "ranged"):
            fparts.append(v)
    if cfg.get("formula"):
        fparts.append(cfg["formula"])
    act = None
    if cfg.get("activity"):
        act = ctx.act(cfg["activity"])
    elif not fparts:
        act = next(iter(ctx.acts(["attack"])), None)
    if label:
        return label
    if act:
        b = attack_bonus(ctx, act)
        formula = signed(b) if b is not None else ""
    else:
        f, _ = simplify(" ".join(fparts), ctx.rolldata())
        formula = f if f.startswith(("+", "-")) else f"+{f}"
    short = f"{formula} to hit" if ctx.rules == "2014" and formula else formula
    if not extended or not act:
        return short or "an attack roll"
    types = attack_types(ctx.item, act)
    tlabel = or_list([t.capitalize() for t in types])
    if ctx.rules == "2014":
        cls = g(act, "attack", "type", "classification") or ("spell" if ctx.item["type"] == "spell" else "weapon")
        kind = f"{tlabel} {cls.capitalize()} Attack"
    else:
        kind = f"{tlabel} Attack Roll"
    parts = [short, weapon_range_label(ctx.item, act, types)]
    if ctx.rules == "2014":
        parts.append(affects_labels(act_field(ctx.item, act, "target"))[1])
    return f"{kind}: " + ", ".join(p for p in parts if p)


def activity_damage(ctx, act, attack_mode=None):
    """[(formula, [types])] for an activity, including the weapon's base damage and ability modifier."""
    out = []
    rd = ctx.rolldata()
    if act.get("type") == "heal":
        h = act.get("healing") or {}
        f = damage_formula(h)
        rd = {**rd, "mod": ability_mod(ctx.A, ctx.A["spell_ability"]) if ctx.A else 0}
        return [(simplify(f, rd), h.get("types") or ["healing"])] if f else []
    s = ctx.item.get("system") or {}
    parts = list(g(act, "damage", "parts", default=[]) or [])
    is_weapon = ctx.item["type"] == "weapon"
    if act.get("type") == "attack":
        ab = attack_ability(ctx, act)
        rd = {**rd, "mod": ability_mod(ctx.A, ab)}
        base = g(s, "damage", "base")
        if g(act, "damage", "includeBase", default=True) and is_weapon and base and (
                base.get("denomination") or g(base, "custom", "enabled")):
            b = dict(base)
            if attack_mode == "twoHanded" and "ver" in (s.get("properties") or []):
                ver = g(s, "damage", "versatile") or {}
                b = {**b, "number": ver.get("number") or b.get("number"),
                     "denomination": ver.get("denomination") or (b.get("denomination") or 0) + 2}
            f = damage_formula(b)
            if re.search(r"\d*d\d+", f) and "@mod" not in f and not (
                    g(act, "attack", "type", "classification") == "spell" and g(s, "type", "value") == "natural"):
                f += " + @mod"
            magic = evaluate(substitute(str(s.get("magicalBonus") or 0), rd)) or 0
            if magic:
                f += f" + {magic}"
            out.append((f, b.get("types") or []))
    elif ctx.A:
        rd = {**rd, "mod": ability_mod(ctx.A, ctx.A["spell_ability"]) if ctx.item["type"] == "spell" else 0}
    for p in parts:
        f = damage_formula(p)
        if f:
            out.append((f, p.get("types") or []))
    return [(simplify(f, rd), t) for f, t in out]


def damage_text(parts, rules, average, fmt=None):
    """Render [((formula, avg), types)] like the dnd5e damage enricher."""
    rendered = []
    for (formula, avg), types in parts:
        labels = [DAMAGE_TYPES.get(t) or HEALING_TYPES.get(t) or "" for t in types]
        tl = or_list([x for x in labels if x])
        if rules == "2014":
            tl = tl.lower()
        if average and avg is not None and str(avg) != formula:
            rendered.append(f"{avg} ({formula}) {tl}".strip())
        else:
            rendered.append(f"{formula} {tl}".strip())
    if average and len(rendered) == 2:
        text = f"{rendered[0]} plus {rendered[1]}"
    else:
        text = and_list(rendered)
    if fmt in ("long", "extended"):
        text = f"{text} damage"
        if fmt == "extended":
            text = f"Hit: {text}"
    return text


def enrich_damage(cfg_str, label, ctx, healing=False):
    configs = [parse_config(c) for c in cfg_str.split("&")]
    average, fmt, activity, attack_mode = False, None, None, None
    explicit = []
    for c in configs:
        types = [t for t in re.split(r"[|/]", c.get("type", "")) if t]
        fparts = []
        activity = c.get("activity") or activity
        attack_mode = c.get("attackMode") or attack_mode
        if c.get("average"):
            average = c["average"] if c["average"] not in ("true", "false") else c["average"] == "true"
        fmt = c.get("format") or fmt
        if c.get("formula"):
            fparts.append(c["formula"])
        for v in c["values"]:
            sv = slug(v)
            if sv in DAMAGE_TYPES or sv in HEALING_TYPES:
                types.append(sv)
            elif v in ("oneHanded", "twoHanded", "offhand", "thrown", "thrown-offhand", "ranged"):
                attack_mode = v
            elif sv == "average":
                average = True
            elif sv == "extended":
                fmt = "extended"
            elif sv == "temp":
                types.append("temphp")
            else:
                fparts.append(v)
        if healing and not types:
            types.append("healing")
        if fparts:
            explicit.append((" ".join(fparts), types))
    if fmt == "extended" and not average:
        average = True
    if label:
        return label
    if explicit:
        rd = ctx.rolldata()
        parts = [(simplify(f, rd), t) for f, t in explicit]
        parts = [((humanize(f), avg), t) for (f, avg), t in parts]
    else:
        act = ctx.act(activity) if activity else None
        if not act:
            types = ["heal"] if healing else ["attack", "damage", "save"]
            act = next((a for a in ctx.acts(types) if g(a, "damage", "parts") or g(a, "healing", "denomination")
                        or g(a, "healing", "custom", "formula") or (a.get("type") == "attack"
                                                                    and ctx.item["type"] == "weapon")), None)
        if not act:
            return ""
        parts = activity_damage(ctx, act, attack_mode)
        if not ctx.A:
            # without an actor the modifier is unknown; keep it symbolic rather than printing +0
            parts = [((re.sub(r" \+ 0$", " + mod", f), None) if " + 0" in f else (f, avg), t) for (f, avg), t in parts]
    if isinstance(average, str) and average.isdigit():
        parts = [((f, int(average)), t) for (f, _), t in parts]
    return damage_text(parts, ctx.rules, bool(average), fmt)


def save_dc(ctx, act):
    dc = g(act, "save", "dc") or g(act, "check", "dc") or {}
    calc = dc.get("calculation")
    if calc == "initial" or calc is None:
        calc = "spellcasting" if ctx.item and ctx.item["type"] == "spell" else ""
    if not ctx.A:
        return evaluate(substitute(dc.get("formula") or "", {})) if not calc else None
    if calc == "spellcasting":
        return ctx.A["spell_dc"]
    if calc in ABILITIES:
        return ctx.A["abilities"][calc]["dc"]
    return evaluate(substitute(dc.get("formula") or "", ctx.rolldata()))


def enrich_save(cfg, label, ctx, concentration=False):
    abilities = [a for a in re.split(r"[|/]", cfg.get("ability", "")) if a]
    dc = cfg.get("dc")
    for v in cfg["values"]:
        k = ability_key(v)
        if k:
            abilities.append(k)
        elif str(v).isdigit():
            dc = v
        else:
            cfg[v] = True
    abilities = [ability_key(a) for a in abilities if ability_key(a)]
    act = None
    if cfg.get("activity"):
        act = ctx.act(cfg["activity"])
    elif not abilities:
        act = next(iter(ctx.acts(["save"])), None)
    if act and act.get("type") == "save":
        ab = g(act, "save", "ability", default=[])
        abilities = [ab] if isinstance(ab, str) else list(ab)
        dc = save_dc(ctx, act)
    if dc not in (None, "") and not str(dc).isdigit():
        dc = evaluate(substitute(dc, ctx.rolldata())) if ctx.A or "@" not in str(dc) else None
    if label:
        return label
    if concentration:
        text = "Concentration"
    else:
        text = or_list([ABILITIES.get(a, a) for a in abilities])
    if dc and not cfg.get("hideDC"):
        text = f"DC {dc} {text}"
    if cfg.get("format") == "long":
        text += " saving throw"
    return text


def enrich_check(cfg, label, ctx):
    ability = ability_key(cfg["ability"]) if cfg.get("ability") else None
    skills = [s for s in re.split(r"[|/]", cfg.get("skill", "")) if s]
    tools = [t for t in re.split(r"[|/]", cfg.get("tool", "")) if t]
    dc = cfg.get("dc")
    for v in cfg["values"]:
        sv = slug(v)
        if ability_key(v):
            ability = ability_key(v)
        elif v in SKILLS or sv in SKILL_SLUG:
            skills.append(v if v in SKILLS else SKILL_SLUG[sv])
        elif v in TOOLS:
            tools.append(v)
        elif str(v).isdigit():
            dc = v
        else:
            cfg[v] = True
    act = None
    if cfg.get("activity"):
        act = ctx.act(cfg["activity"])
    elif not (ability or skills or tools):
        act = next(iter(ctx.acts(["check"])), None)
    if act and act.get("type") == "check":
        ability = g(act, "check", "ability") or ability
        assoc = g(act, "check", "associated", default=[]) or []
        skills = [a for a in assoc if a in SKILLS]
        tools = [a for a in assoc if a not in SKILLS]
        dc = g(act, "check", "dc", "value") or save_dc(ctx, act)
    skills = [s if s in SKILLS else SKILL_SLUG.get(slug(s), s) for s in skills]
    if dc not in (None, "") and not str(dc).isdigit():
        dc = evaluate(substitute(dc, ctx.rolldata())) if ctx.A or "@" not in str(dc) else None
    if label:
        return label
    groups = defaultdict(list)
    for sk in skills:
        if sk in SKILLS:
            groups[ability or SKILLS[sk][1]].append(SKILLS[sk][0])
    for t in tools:
        groups[ability or ""].append(TOOLS.get(t, t))
    if groups:
        parts = []
        for ab, assoc in groups.items():
            parts.append(f"{ABILITIES[ab]} ({or_list(assoc)})" if ab in ABILITIES else or_list(assoc))
        text = or_list(parts)
    else:
        text = ABILITIES.get(ability, "")
    if cfg.get("passive"):
        return f"passive {text} score of {dc} or higher" if dc and cfg.get("format") == "long" else (
            f"DC {dc} passive {text}" if dc else f"passive {text}")
    if dc and not cfg.get("hideDC"):
        text = f"DC {dc} {text}"
    if cfg.get("format") == "long" or len(skills) + len(tools) > 1:
        text += " check"
    return text


def rule_name(key):
    k = slug(key)
    return RULE_NAMES.get(k) or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key).strip().title()


def enrich_lookup(cfg, fallback, ctx):
    path, style = cfg.get("path"), cfg.get("style")
    for v in cfg["values"]:
        if v in ("capitalize", "lowercase", "uppercase"):
            style = style or v
        elif v.startswith("@"):
            path = path or v
    if not path:
        return fallback or ""
    p = path[1:]
    if cfg.get("activity"):
        act = ctx.act(cfg["activity"])
        if not act:
            return fallback or ""
        data = activity_rolldata(ctx.item, act)
        if p == "save.dc.value":
            value = save_dc(ctx, act)
        elif p == "check.dc.value":
            value = g(act, "check", "dc", "value") or save_dc(ctx, act)
        else:
            value = lookup_path(data, p)
        if isinstance(value, dict):
            value = None
    else:
        value = scale_text(p) if p.startswith("scale.") and not ctx.A else lookup_path(ctx.rolldata(), p)
        if value is None and ctx.item and p.startswith(("labels.", "target.", "range.", "duration.")):
            act = next(iter(ctx.acts()), {}) or {}
            value = lookup_path(activity_rolldata(ctx.item, act), p)
    if value in (None, "") or isinstance(value, (dict, list)):
        value = fallback
    if value in (None, ""):
        return ""
    value = str(value)
    if style == "capitalize":
        value = cap(value)
    elif style == "lowercase":
        value = value.lower()
    elif style == "uppercase":
        value = value.upper()
    return value


def scale_value(cfg_type, v, units=""):
    if cfg_type == "dice":
        return f"{v.get('number') or 1}d{v.get('faces')}" if v.get("faces") else ""
    if cfg_type == "distance":
        return length(v.get("value"), units or "ft")
    val = v.get("value")
    return "" if val is None else "Unlimited" if val == 999 else str(val)


def scale_text(path):
    """'@scale.monk.die' -> 'Martial Arts Die (1d6; level 5 1d8; ...)': the class table column."""
    key = path.split(".", 1)[1] if path.startswith("scale.") else path
    adv = SCALES.get((EDITION[0], key.rsplit(".", 1)[0] if key.count(".") > 1 else key))
    if not adv:
        return None
    c = adv["configuration"]
    steps = sorted(c.get("scale", {}).items(), key=lambda kv: int(kv[0]))
    vals = [(lvl, scale_value(c.get("type"), v, g(c, "distance", "units"))) for lvl, v in steps]
    vals = [(lvl, v) for lvl, v in vals if v]
    if not vals:
        return adv.get("title")
    seq = "; ".join(f"level {lvl} {v}" if i else (v if lvl == "1" else f"level {lvl} {v}")
                    for i, (lvl, v) in enumerate(vals))
    return f"{adv.get('title')} ({seq})"


def enrich_item(cfg, label, ctx):
    given = " ".join(cfg["values"])
    if label:
        return label
    act_name = cfg.get("activity")
    if given.startswith(".") or given.startswith("Compendium.") or given.startswith("Actor."):
        parts = given.split(".")
        ids = [p for p in parts if re.fullmatch(r"[A-Za-z0-9]{16}", p)]
        name = None
        if "Activity" in parts and len(ids) >= 2:
            item = next((i for i in (ctx.A or {}).get("items", []) if i["_id"] == ids[-2]), None) or DOCS.get(ids[-2])
            act = (g(item, "system", "activities", default={}) or {}).get(ids[-1]) if item else None
            if item:
                name = f"{item['name']} ({act.get('name')})" if act and act.get("name") else item["name"]
        elif ids:
            item = next((i for i in (ctx.A or {}).get("items", []) if i["_id"] == ids[-1]), None) or DOCS.get(ids[-1])
            name = item["name"] if item else None
        return name or ""
    if ctx.A:
        item = next((i for i in ctx.A["items"] if i["_id"] == given), None)
        if item:
            given = item["name"]
    if not given and ctx.item:
        given = ctx.item["name"]
    return f"{given} ({act_name})" if act_name else given


def enrich_award(cfg_str, label):
    out = []
    each = False
    for part in cfg_str.split():
        m = re.fullmatch(r"([\d.,]+|\[\[.*?\]\]|\S+?)(pp|gp|ep|sp|cp|xp)", part, re.I)
        if m:
            amt, unit = m.group(1), m.group(2).lower()
            out.append(f"{amt} {'XP' if unit == 'xp' else unit}")
        elif part.lower() == "each":
            each = True
    text = ", ".join(out)
    return f"{text} each" if each else text or (label or "")


def free_rules(html_):
    """Pages from the D&D Free Rules that the system marks as not CC-BY and not to be redistributed outside it."""
    return isinstance(html_, str) and "Free Rules content" in html_


def doc_by_uuid(uuid):
    parts = uuid.split(".")
    ids = [p for p in parts if re.fullmatch(r"[A-Za-z0-9]{16}", p)]
    if not ids:
        return None
    if parts[0] == "Compendium" and len(parts) > 2:
        doc = PACK_DOCS.get((parts[2], ids[-1]))
        if doc:
            return doc
    return DOCS.get(ids[-1])


def enrich_embed(target, opts, ctx):
    doc = doc_by_uuid(target)
    if not doc:
        return ""
    if "pages" in doc or "text" in doc and isinstance(doc.get("text"), dict):  # journal entry or page
        if ctx.depth >= 2:
            return f" (see {doc['name']}) "
        html_ = g(doc, "text", "content") or g(doc, "system", "description", "value") or ""
        if not html_ and "pages" in doc:
            html_ = " ".join(g(DOCS.get(p), "text", "content", default="") for p in doc["pages"])
        if free_rules(html_):
            return ""
        return " / " + resolve(html_, Ctx(rules=ctx.rules, depth=ctx.depth + 1)) + " / "
    if "results" in doc:
        return f" (table: {doc['name']}) "
    if doc.get("type") in ("npc", "vehicle", "character"):
        return f" (stat block: {doc['name']}) "
    return f" {doc['name']} "


ROLL_CMD = re.compile(r"\[\[/(\w+)(?:\s+((?:[^\[\]]|\[[^\]]*\])*?))?\s*\]\](?:\{([^}]*)\})?")
INLINE_ROLL = re.compile(r"\[\[((?:[^\[\]]|\[[^\]]*\])*)\]\](?:\{([^}]*)\})?")
LOOKUP = re.compile(r"\[\[lookup\s+([^\]]*)\]\](?:\{([^}]*)\})?")
LINK = re.compile(r"@(UUID|Compendium)\[([^\]]+)\](?:\{([^}]*)\})?")
EMBED = re.compile(r"@[Ee]mbed\[(\S+?)(\s[^\]]*)?\](?:\{([^}]*)\})?")
REFERENCE = re.compile(r"&(?:amp;)?[Rr]eference\[([^\]}]+)[\]}](?:\{([^}]*)\})?")
OTHER_AT = re.compile(r"@(\w+)\[([^\]]+)\](?:\{([^}]*)\})?")


def resolve(text, ctx):
    """Render Foundry/dnd5e enrichers in an HTML string to plain text."""
    if not text or not isinstance(text, str):
        return ""
    # GM-only secret sections (Foundry implementation notes, hidden when Foundry renders) and "fvtt advice" boxes
    # (how to use Foundry's character sheet) aren't rules text
    text = re.sub(r'<section[^>]*class="[^"]*\b(?:secret|fvtt)\b[^"]*"[^>]*>.*?</section>', "", text, flags=re.S)
    text = re.sub(r"(\[\[lookup [^\]}]*)\]\}\{", r"\1]]{", text)
    text = EMBED.sub(lambda m: enrich_embed(m.group(1), m.group(2) or "", ctx), text)
    text = LOOKUP.sub(lambda m: enrich_lookup(parse_config(m.group(1)), m.group(2), ctx), text)

    def roll(m):
        cmd, cfg, label = m.group(1).lower(), m.group(2) or "", m.group(3)
        if cmd == "attack":
            return enrich_attack(parse_config(cfg), label, ctx)
        if cmd in ("damage", "heal", "healing"):
            return enrich_damage(cfg, label, ctx, healing=cmd != "damage")
        if cmd in ("save", "concentration"):
            return enrich_save(parse_config(cfg), label, ctx, concentration=cmd == "concentration")
        if cmd in ("check", "skill", "tool"):
            return enrich_check(parse_config(cfg), label, ctx)
        if cmd == "item":
            return enrich_item(parse_config(cfg), label, ctx)
        if cmd == "award":
            return enrich_award(cfg, label)
        if cmd == "reference":
            return label or rule_name(cfg)
        if cmd == "language":
            return label or LANGUAGES.get(slug(cfg), cfg)
        if label:
            return label
        f = cfg.split("#")[0].strip()
        if "@" in f:
            sf, _ = simplify(f, ctx.rolldata())
            f = sf if "@" not in sf else humanize(f)
        return f

    text = ROLL_CMD.sub(roll, text)

    def inline(m):
        if m.group(2):
            return m.group(2)
        f = m.group(1).split("#")[0].strip()
        v = evaluate(substitute(f, ctx.rolldata())) if "@" in f else None
        return str(v) if v is not None else f

    text = INLINE_ROLL.sub(inline, text)
    text = LINK.sub(lambda m: m.group(3) or (doc_by_uuid(m.group(2)) or {}).get("name", m.group(2).split(".")[-1]),
                    text)
    text = REFERENCE.sub(lambda m: m.group(2) or rule_name(m.group(1).split()[0]), text)
    text = OTHER_AT.sub(lambda m: m.group(3) or m.group(2).split("|")[0], text)
    return text


# ---------------------------------------------------------------- text

TAG_BLOCK = re.compile(r"</?(p|div|li|ul|ol|h[1-6]|tr|table|thead|tbody|section|blockquote|aside|figure|dl|dt|dd)"
                       r"\b[^>]*>", re.I)


def clean(s) -> str:
    if not s or not isinstance(s, str):
        return ""
    s = re.sub(r"(<t[dh][^>]*>)\s*<p[^>]*>", r"\1", s, flags=re.I)  # paragraphs inside table cells
    s = re.sub(r"</p>\s*(</t[dh]>)", r"\1", s, flags=re.I)
    s = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r" /[\1]/ ", s, flags=re.S | re.I)
    s = re.sub(r"<hr\s*/?>", " / ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", " / ", s, flags=re.I)
    s = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", ",", s, flags=re.I)
    s = re.sub(r"</tr>", ";", s, flags=re.I)
    s = re.sub(r"<(caption)[^>]*>(.*?)</\1>", r" /[\2]/ ", s, flags=re.S | re.I)
    s = TAG_BLOCK.sub(" / ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("|", "¦")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r" ([,.;:)])", r"\1", s)
    s = re.sub(r"/\[\s*([^\]]*?)\s*\]/", r" /[\1]/ ", s)
    s = re.sub(r"/\[\]/", "", s)
    # separators are always ' / ' with spaces; a bare slash (1/Day, 80/320 ft) is text
    s = re.sub(r"\s+/(?:\s+/)*\s+", " / ", f" {s} ")
    s = re.sub(r" / (/\[)", r" \1", s)
    s = re.sub(r"(\]/) / ", r"\1 ", s)
    s = re.sub(r"\s*;\s*(/\s+)?", "; ", s)
    s = re.sub(r"\s+/\s*([,;])", r"\1", s)
    s = re.sub(r"([,;])\s*/\s+", r"\1 ", s)
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"^(?:\s*/\s+|[\s;])+|(?:\s+/\s*|[\s;])+$", "", s)


def text_of(html_, ctx):
    return clean(resolve(html_, ctx))


def rec(*fields) -> str:
    return "|".join(str(f) for f in fields if f not in (None, ""))


def lab(k, v):
    v = clean(str(v)) if v not in (None, "") else ""
    return f"{k}:{v}" if v else ""


# ---------------------------------------------------------------- shared labels

def uses_label(item):
    """'Recharge 5–6', '3/Day', 'Recharge after a Long Rest', like UsesField.getStatblockLabel."""
    s = item.get("system") or {}
    acts = sorted_activities(item)
    act = acts[0] if len(acts) == 1 else None
    activation = g(act, "activation") or {}
    if activation.get("type") in ("legendary", "mythic"):
        v = activation.get("value")
        return f"Costs {v} Actions" if v and int(v) >= 2 else ""
    for u in (s.get("uses") or {}, (act or {}).get("uses") or {}):
        mx = u.get("max")
        rec_ = u.get("recovery") or []
        if not mx or len(rec_) != 1:
            continue
        r = rec_[0]
        if r.get("period") == "recharge":
            v = int(r.get("formula") or 6)
            return "Recharge 6" if v == 6 else f"Recharge {v}–6"
        if r.get("period") in ("lr", "sr") and str(mx) == "1":
            return "Recharge after a Short or Long Rest" if r["period"] == "sr" else "Recharge after a Long Rest"
        if r.get("period") in ("lr", "sr", "day", "dawn", "dusk"):
            per = "Short Rest" if r["period"] == "sr" else "Day"
            mxv = evaluate(str(mx)) if not str(mx).isdigit() else mx
            return f"{mxv if mxv is not None else mx}/{per}"
    return ""


def item_uses(item):
    """Uses for a feature/item record: '2/Long Rest', 'Recharge 5–6', '7 charges; regains 1d6 + 1 at Dawn'."""
    u = g(item, "system", "uses") or {}
    mx = u.get("max")
    if not mx:
        return ""
    mx = humanize(mx)
    rec_ = u.get("recovery") or []
    parts = []
    for r in rec_:
        p = r.get("period")
        if p == "recharge":
            v = int(r.get("formula") or 6)
            return "Recharge 6" if v == 6 else f"Recharge {v}–6"
        per = PERIODS.get(p, p)
        if r.get("type") == "formula" and r.get("formula"):
            parts.append(f"regains {r['formula']} at {per}")
        else:
            parts.append(per)
    plain = [x for x in parts if not x.startswith("regains")]
    partial = [x for x in parts if x.startswith("regains")]
    noun = "uses" if item["type"] == "feat" else "charges"
    if not parts:
        return "" if str(mx) == "1" else f"{mx} {noun}"
    base = f"{mx}/{' or '.join(plain)}" if plain else f"{mx} {noun}"
    return "; ".join([base] + partial)


def item_activation(item):
    acts = sorted_activities(item)
    a = act_field(item, acts[0], "activation") if acts else g(item, "system", "activation") or {}
    t = a.get("type") or ""
    if not t or t == "none":
        return ""
    lab_ = activation_label(a)
    if a.get("condition"):
        lab_ += f", {text_of(a['condition'], Ctx(item))}"
    return lab_


def price(s):
    p = s.get("price") or {}
    v = p.get("value")
    return f"{fmt_num(v)} {CURRENCY.get(p.get('denomination'), p.get('denomination') or 'gp')}" if v else ""


def weight(s):
    w = s.get("weight") or {}
    v = w.get("value") if isinstance(w, dict) else w
    return f"{fmt_num(v)} {w.get('units') or 'lb'}" if v else ""


# ---------------------------------------------------------------- formatters

def f_spell(d, ed, extra):
    s = d["system"]
    lvl = s.get("level") or 0
    props = s.get("properties") or []
    comps = [c for k, c in (("vocal", "V"), ("somatic", "S"), ("material", "M")) if k in props]
    mat = g(s, "materials", "value")
    if "M" in comps and mat:
        comps[-1] = f"M ({mat})"
    acts = sorted_activities(d)
    act = acts[0] if acts else {}
    activation = act_field(d, act, "activation") or {}
    time = activation_label(activation) if activation.get("type") else ""
    if activation.get("value") and str(activation.get("value")) not in ("1", "") and activation.get("type") in (
            "action", "bonus", "reaction"):
        time = f"{activation['value']} {time}s"
    if activation.get("condition"):
        time += f", {text_of(activation['condition'], Ctx(d, None, ed))}"
    if "ritual" in props:
        time += " or Ritual"
    rng = act_field(d, act, "range") or {}
    rl = range_label(rng, long=True) if rng else ""
    if rng.get("special"):
        rl = f"{rl} ({rng['special']})" if rl else rng["special"]
    area = area_label(g(act_field(d, act, "target"), "template", default={}) or {})
    if area and rl in ("Self", ""):
        rl = f"Self ({area})"
    dur = act_field(d, act, "duration") or {}
    dl = humanize(duration_label(dur))
    if "concentration" in props:
        dl = f"Concentration, up to {dl}" if dl and dl[0].isdigit() else f"Concentration ({dl})"
    classes = extra.get("classes", {}).get(d["_id"], {})
    ctx = Ctx(d, None, ed)
    return rec(d["name"], "spell", lab("level", "cantrip" if lvl == 0 else lvl), lab("school", SCHOOLS.get(s.get("school"))),
               lab("time", time), lab("range", rl), lab("components", ", ".join(comps)), lab("duration", dl),
               lab("classes", ", ".join(sorted(classes.get("class", [])))),
               lab("subclasses", ", ".join(sorted(classes.get("subclass", [])))),
               text_of(g(s, "description", "value"), ctx))


def levels_table(d, ed):
    """'1: Rage, Unarmored Defense; 2: Danger Sense; ...' from a class/subclass's advancement."""
    by = defaultdict(list)
    scales = []
    for a in advancements(d):
        t, lvl = a.get("type"), a.get("level")
        if t == "ItemGrant" and lvl is not None:
            for it in g(a, "configuration", "items", default=[]) or []:
                uuid = it.get("uuid") if isinstance(it, dict) else it
                doc = doc_by_uuid(uuid or "")
                if doc:
                    by[lvl].append(doc["name"])
        elif t == "ItemChoice" and lvl is not None:
            by[lvl].append(a.get("title") or "choice")
        elif t == "Subclass":
            by[lvl].append(f"{d['name']} Subclass")
        elif t == "AbilityScoreImprovement" and lvl is not None:
            by[lvl].append("Ability Score Improvement" if ed == "2014" else "Ability Score Improvement (feat)")
        elif t == "ScaleValue":
            c = a.get("configuration") or {}
            steps = sorted((c.get("scale") or {}).items(), key=lambda kv: int(kv[0]))
            vals = [f"{lv} {scale_value(c.get('type'), v, g(c, 'distance', 'units'))}" for lv, v in steps]
            if vals:
                scales.append(f"{a.get('title')}: " + ", ".join(vals))
    feats = "; ".join(f"{lvl}: {', '.join(dict.fromkeys(names))}" for lvl, names in sorted(by.items()) if names)
    return feats, " / ".join(scales)


def f_class(d, ed, extra):
    s = d["system"]
    feats, scales = levels_table(d, ed)
    sc = s.get("spellcasting") or {}
    prog = sc.get("progression")
    casting = f"{prog} ({ABILITIES.get(sc.get('ability'), sc.get('ability'))})" if prog and prog != "none" else ""
    prim = g(s, "primaryAbility", "value", default=[])
    joiner = " and " if g(s, "primaryAbility", "all") else " or "
    return rec(d["name"], "class", lab("hd", g(s, "hd", "denomination")),
               lab("primary", joiner.join(ABILITIES.get(p, p) for p in prim)), lab("spellcasting", casting),
               lab("features", feats), lab("scale", scales), text_of(g(s, "description", "value"), Ctx(d, None, ed)))


def f_subclass(d, ed, extra):
    s = d["system"]
    feats, scales = levels_table(d, ed)
    cls = s.get("classIdentifier") or ""
    sc = s.get("spellcasting") or {}
    prog = sc.get("progression")
    return rec(d["name"], "subclass", lab("class", cls.replace("-", " ").title()),
               lab("spellcasting", f"{prog} ({ABILITIES.get(sc.get('ability'), '')})" if prog and prog != "none"
                   else ""), lab("features", feats), lab("scale", scales),
               text_of(g(s, "description", "value"), Ctx(d, None, ed)))


def f_feature(d, ed, extra):
    s = d["system"]
    t = s.get("type") or {}
    tv, sub = t.get("value") or "", t.get("subtype") or ""
    kind = "feat" if tv == "feat" else "feature"
    typ = FEATURE_TYPES.get(tv, tv)
    if sub:
        typ = f"{typ} ({FEAT_SUBTYPES.get(sub, sub)})" if typ else FEAT_SUBTYPES.get(sub, sub)
    req = s.get("requirements") or ""
    lvl = g(s, "prerequisites", "level")
    granted = GRANTED.get(d["_id"], "")
    if granted:
        req = granted
    elif lvl and tv == "class" and req and not re.search(r"\d", req):
        req = f"{req} {lvl}"
    prereq = f"level {lvl}+" if lvl and tv == "feat" else ""
    rep = "yes" if g(s, "prerequisites", "repeatable") else ""
    return rec(d["name"], kind, lab("type", typ), lab("granted" if granted else "requires", req),
               lab("prerequisite", prereq),
               lab("repeatable", rep), lab("uses", item_uses(d)), lab("activation", item_activation(d)),
               text_of(g(s, "description", "value"), Ctx(d, None, ed)))


def f_species(d, ed, extra):
    s = d["system"]
    size = ""
    traits = []
    for a in advancements(d):
        if a.get("type") == "Size":
            size = a.get("hint") or ", ".join(SIZES.get(x, x) for x in g(a, "configuration", "sizes", default=[]))
        elif a.get("type") == "ItemGrant":
            for it in g(a, "configuration", "items", default=[]) or []:
                doc = doc_by_uuid((it.get("uuid") if isinstance(it, dict) else it) or "")
                if doc:
                    traits.append(doc["name"])
    mv = s.get("movement") or {}
    speed = ", ".join(([length(mv["walk"], mv.get("units") or "ft")] if mv.get("walk") else []) +
                      [f"{MOVEMENT[k]} {length(mv[k], mv.get('units') or 'ft')}" for k in MOVEMENT
                       if k != "walk" and mv.get(k)])
    se = s.get("senses") or {}
    senses = ", ".join(f"{SENSES[k]} {length(se[k], se.get('units') or 'ft')}" for k in SENSES if se.get(k))
    t = s.get("type") or {}
    return rec(d["name"], "species", lab("type", CREATURE_TYPES.get(t.get("value"), t.get("custom"))),
               lab("size", size), lab("speed", speed), lab("senses", senses), lab("traits", ", ".join(traits)),
               text_of(g(s, "description", "value"), Ctx(d, None, ed)))


def f_background(d, ed, extra):
    s = d["system"]
    grants = []
    for a in advancements(d):
        if a.get("type") == "ItemGrant":
            for it in g(a, "configuration", "items", default=[]) or []:
                doc = doc_by_uuid((it.get("uuid") if isinstance(it, dict) else it) or "")
                if doc:
                    grants.append(doc["name"])
    return rec(d["name"], "background", lab("grants", ", ".join(grants)),
               text_of(g(s, "description", "value"), Ctx(d, None, ed)))


def armor_text(s):
    a = s.get("armor") or {}
    t = g(s, "type", "value")
    v = a.get("value")
    if v is None:
        return ""
    if t == "shield":
        return f"+{v}"
    if t == "heavy" or a.get("dex") == 0:
        return str(v)
    return f"{v} + Dex modifier (max {a['dex']})" if a.get("dex") else f"{v} + Dex modifier"


def f_equipment(d, ed, extra):
    s = d["system"]
    t = d["type"]
    tv = g(s, "type", "value") or ""
    sub = g(s, "type", "subtype") or ""
    props = s.get("properties") or []
    typ = {"weapon": WEAPON_TYPES, "equipment": EQUIP_TYPES, "consumable": CONSUMABLE_TYPES, "tool": TOOL_TYPES,
           "loot": LOOT_TYPES}.get(t, {}).get(tv, tv)
    if sub and t == "consumable":
        typ = f"{typ} ({sub})"
    kind = {"equipment": "armor" if tv in ARMOR_TYPES else "gear"}.get(t, t)
    dmg = ver = rng = mastery = ""
    if t == "weapon":
        base = g(s, "damage", "base") or {}
        if base.get("denomination") or g(base, "custom", "enabled"):
            dmg = f"{humanize(damage_formula(base))} {or_list([DAMAGE_TYPES.get(x, x) for x in base.get('types') or []])}".strip()
        v = g(s, "damage", "versatile") or {}
        if "ver" in props:
            ver = f"{v.get('number') or base.get('number') or 1}d{v.get('denomination') or (base.get('denomination') or 0) + 2}"
        r = s.get("range") or {}
        if r.get("value"):
            rng = f"{fmt_num(r['value'])}/{length(r['long'], r.get('units'))}" if r.get("long") and r["long"] != r["value"] \
                else length(r["value"], r.get("units"))
        mastery = cap(s.get("mastery") or "")
    uses = item_uses(d)
    mb = s.get("magicalBonus")
    att = {"required": "required", "optional": "optional"}.get(s.get("attunement"), s.get("attunement") or "")
    ctx = Ctx(d, None, ed)
    return rec(d["name"], kind, lab("type", typ), lab("damage", dmg), lab("versatile", ver),
               lab("properties", ", ".join(ITEM_PROPERTIES.get(p, p) for p in props
                                           if p not in ("mgc", "foc", "trait", "weightlessContents"))),
               lab("mastery", mastery), lab("range", rng),
               lab("ac", armor_text(s) if t == "equipment" else ""), lab("strength", s.get("strength")),
               lab("bonus", f"+{mb}" if mb else ""), lab("rarity", RARITY.get(s.get("rarity"), s.get("rarity"))),
               lab("attunement", att), lab("uses", uses), lab("price", price(s)), lab("weight", weight(s)),
               text_of(g(s, "description", "value"), ctx))


def creature_type(t):
    if not t:
        return ""
    if t.get("swarm"):
        base = CREATURE_PLURAL.get(t.get("value"), CREATURE_TYPES.get(t.get("value"), "") + "s")
        out = f"Swarm of {SIZES.get(t['swarm'], t['swarm'])} {base}"
    else:
        out = CREATURE_TYPES.get(t.get("value")) or t.get("custom") or ""
    if t.get("subtype"):
        out += f" ({t['subtype']})"
    return out


def trait_list(tr, labels=None):
    if not tr:
        return ""
    vals = [(labels or {}).get(v, DAMAGE_TYPES.get(v, v.capitalize() if isinstance(v, str) else v))
            for v in tr.get("value") or []]
    vals += [x.strip() for x in (tr.get("custom") or "").split(";") if x.strip()]
    if tr.get("bypasses") and any(v in DAMAGE_TYPES for v in tr.get("value") or []):
        phys = [v for v in tr["value"] if v in ("bludgeoning", "piercing", "slashing")]
        rest = [x for x in vals if x.lower() not in phys]
        bp = or_list([ITEM_PROPERTIES.get(b, b) for b in tr["bypasses"]])
        vals = rest + [f"{and_list([DAMAGE_TYPES[p] for p in phys])} from attacks that are not {bp}"]
    return ", ".join(sorted(vals, key=str.lower))


def f_monster(d, ed, extra):
    A = derive(d)
    s = d["system"]
    rules = A["rules"] or ed
    att = s.get("attributes") or {}
    details = s.get("details") or {}
    traits = s.get("traits") or {}
    tag = f"{SIZES.get(traits.get('size'), '')} {creature_type(details.get('type'))}".strip()
    if details.get("alignment"):
        tag += f", {details['alignment']}"
    if rules == "2014":
        tag = cap(tag.lower())
    ac, ac_label = armor_class(A)
    hp = att.get("hp") or {}
    hp_text = f"{hp.get('max')} ({hp['formula']})" if hp.get("formula") else str(hp.get("max") or "")
    mv = att.get("movement") or {}
    units = mv.get("units") or "ft"
    sp = [length(mv["walk"], units)] if mv.get("walk") else []
    for k in ("burrow", "climb", "fly", "swim"):
        if mv.get(k):
            x = f"{MOVEMENT[k] if rules == '2024' else MOVEMENT[k].lower()} {length(mv[k], units)}"
            sp.append(f"{x} (hover)" if k == "fly" and mv.get("hover") else x)
    speed = ", ".join(sp) + (f" ({mv['special']})" if mv.get("special") else "")
    abil = ", ".join(f"{k.capitalize()} {v['value']} ({signed(v['mod'])})" for k, v in A["abilities"].items())
    saves = ", ".join(f"{k.capitalize()} {signed(v['save'])}" for k, v in A["abilities"].items() if v["proficient"])
    skills = ", ".join(f"{SKILLS[k][0]} {signed(v['total'])}" for k, v in sorted(A["skills"].items(),
                       key=lambda kv: SKILLS[kv[0]][0]) if v["value"] > 0)
    senses_d = att.get("senses") or {}
    ranges = senses_d.get("ranges") or senses_d
    su = senses_d.get("units") or "ft"
    sen = sorted([f"{SENSES[k] if rules == '2024' else SENSES[k].lower()} {length(ranges[k], su)}" for k in SENSES
                  if ranges.get(k)] + [x.strip() for x in (senses_d.get("special") or "").split(";") if x.strip()],
                 key=str.lower)
    senses = "; ".join(x for x in (", ".join(sen), f"Passive Perception {A['skills']['prc']['passive']}") if x)
    langs = traits.get("languages") or {}
    lang = [LANGUAGES.get(x, x.capitalize()) for x in langs.get("value") or []]
    lang += [x.strip() for x in (langs.get("custom") or "").split(";") if x.strip()]
    for k, v in (langs.get("communication") or {}).items():
        if isinstance(v, dict) and v.get("value"):
            lang.append(f"{k.capitalize() if rules == '2024' else k} {length(v['value'], v.get('units') or 'ft')}")
    cr = A["cr"]
    xp = cr_xp(cr)
    lair = g(s, "resources", "lair", "value")
    if rules == "2024":
        xpt = f"XP {fmt_num(xp)}, or {fmt_num(cr_xp((cr or 0) + 1))} in lair" if lair and cr is not None \
            else f"XP {fmt_num(xp)}"
        crt = f"{cr_text(cr)} ({xpt}; PB {signed(A['prof'])})"
    else:
        crt = f"{cr_text(cr)} ({fmt_num(xp)} XP)"
    dv, dr, di = (trait_list(traits.get(k)) for k in ("dv", "dr", "di"))
    ci = trait_list(traits.get("ci"))
    if rules == "2024" and ci:
        di = "; ".join(x for x in (di, ci) if x)
        ci = ""
    gear = ", ".join(sorted(f"{i['name']}" + (f" ({g(i, 'system', 'quantity')})" if (g(i, 'system', 'quantity') or 1) > 1
                                             else "") for i in A["items"]
                            if "gear" in (g(i, "system", "properties", default=[]) or [])
                            and g(i, "system", "quantity")))
    habitat = ", ".join(x.get("type", "").capitalize() if not x.get("subtype") else
                        f"{x['type'].capitalize()} ({x['subtype']})"
                        for x in g(details, "habitat", "value", default=[]) or [])
    if g(details, "habitat", "custom"):
        habitat = ", ".join(x for x in (habitat, details["habitat"]["custom"]) if x)
    treasure = ", ".join(x.capitalize() for x in g(details, "treasure", "value", default=[]) or [])
    sections = {k: [] for k in ("trait", "action", "bonus", "reaction", "legendary", "mythic", "lair")}
    leg_desc = A["legendary"]
    mythic_desc = ""
    for item in sorted(A["items"], key=lambda i: i.get("sort") or 0):
        if item["type"] not in ("feat", "weapon"):
            continue
        acts = sorted_activities(item)
        if "trait" in (g(item, "system", "properties", default=[]) or []):
            cat = "trait"
        else:
            cat = g(acts[0], "activation", "type") if acts else "trait"
        cat = cat if cat in sections else "trait"
        ctx = Ctx(item, A, rules)
        desc = text_of(g(item, "system", "description", "value"), ctx)
        ident = g(item, "system", "identifier")
        if ident == "legendary-actions":
            leg_desc = desc or leg_desc
            continue
        if ident == "mythic-actions":
            mythic_desc = desc
            continue
        u = uses_label(item)
        if ident == "legendary-resistance":
            legres = g(s, "resources", "legres", "max")
            if legres:
                u = f"{legres}/Day, or {legres + 1}/Day in Lair" if lair and rules == "2024" else f"{legres}/Day"
        name = f"{item['name']} ({u})" if u else item["name"]
        sections[cat].append(f"{name}. {desc}" if desc else name)
    titles = {"trait": "Traits", "action": "Actions", "bonus": "Bonus Actions", "reaction": "Reactions",
              "legendary": "Legendary Actions", "mythic": "Mythic Actions", "lair": "Lair Actions"}
    body = []
    for k, entries in sections.items():
        if not entries:
            continue
        body.append(f"/[{titles[k]}]/")
        if k == "legendary" and leg_desc:
            body.append(leg_desc)
        if k == "mythic" and mythic_desc:
            body.append(mythic_desc)
        body.extend(entries)
    text = " / ".join(body).replace("|", "¦")
    text = re.sub(r"\s+", " ", text)
    line = rec(d["name"], "monster", lab("tag", tag),
               lab("ac", f"{ac} ({ac_label.lower()})" if ac_label and rules == "2014" else ac),
               lab("initiative", f"{signed(A['init'])} ({10 + A['init']})" if rules == "2024" else ""),
               lab("hp", hp_text), lab("speed", speed), lab("abilities", abil), lab("saves", saves),
               lab("skills", skills), lab("vulnerabilities", dv), lab("resistances", dr), lab("immunities", di),
               lab("condition-immunities", ci), lab("gear", gear), lab("senses", senses),
               lab("languages", ", ".join(lang) or ("None" if rules == "2024" else "—")), lab("cr", crt if cr is not None else ""),
               lab("habitat", habitat), lab("treasure", treasure), text)
    return line


def f_vehicle(d, ed, extra):
    s = d["system"]
    att = s.get("attributes") or {}
    t = s.get("traits") or {}
    items = EMBEDDED.get((d.get("_pack"), d["_id"]), [])
    ac = g(att, "ac", "flat") or g(att, "ac", "value")
    hp = g(att, "hp", "max")
    mv = att.get("movement") or {}
    speed = ", ".join(f"{MOVEMENT.get(k, k)} {length(v, mv.get('units') or 'ft')}" for k, v in mv.items()
                      if k in MOVEMENT and v)
    cap_ = att.get("capacity") or {}
    crew = ", ".join(f"{k} {v}" for k, v in cap_.items() if v and not isinstance(v, dict))
    parts = [f"{i['name']}. {text_of(g(i, 'system', 'description', 'value'), Ctx(i, None, ed))}" for i in items
             if i["type"] in ("feat", "weapon", "equipment")]
    desc = text_of(g(s, "details", "biography", "value"), Ctx(None, None, ed))
    return rec(d["name"], "vehicle", lab("size", SIZES.get(t.get("size"))), lab("ac", ac), lab("hp", hp),
               lab("dt", g(att, "hp", "dt")), lab("speed", speed), lab("capacity", crew),
               " / ".join(x for x in [desc] + parts if x))


# ---------------------------------------------------------------- journals and tables

def journal_lines(docs, ed):
    folders = {v["_id"]: v for k, v in docs.items() if k.startswith("!folders!")}
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
        for n, pid in enumerate(j.get("pages") or []):
            p = pages.get(f"{j['_id']}.{pid}")
            if not p or p.get("type") in ("class", "subclass"):
                continue
            first = n == 0 and p["name"] == j["name"]
            name = j["name"] if first else f"{j['name']} > {p['name']}"
            if p.get("type") == "spells":
                by = defaultdict(list)
                for uuid in g(p, "system", "spells", default=[]) or []:
                    doc = doc_by_uuid(uuid)
                    if doc:
                        by[g(doc, "system", "level", default=0)].append(doc["name"])
                for u in g(p, "system", "unlinkedSpells", default=[]) or []:
                    by[u.get("system", {}).get("level", 0) if isinstance(u, dict) else 0].append(
                        u.get("name", "") if isinstance(u, dict) else str(u))
                lists = "; ".join(f"{'Cantrips' if lvl == 0 else f'Level {lvl}'}: {', '.join(sorted(v))}"
                                  for lvl, v in sorted(by.items()))
                desc = text_of(g(p, "system", "description", "value"), Ctx(rules=ed))
                yield "spell-lists", p["name"], "spell list", rec(
                    p["name"], "spell list", lab(g(p, "system", "type") or "list",
                                                 g(p, "system", "identifier")), desc, lists)
                continue
            if free_rules(g(p, "text", "content")):
                continue
            txt = text_of(g(p, "text", "content"), Ctx(rules=ed))
            if not re.sub(r"/\[[^\]]*\]/|\((?:stat block|table): [^)]*\)|[\s/;,]", "", txt):
                continue  # nothing but embedded stat blocks / tables, which have their own records
                continue
            kind = g(p, "system", "type") if p.get("type") == "rule" else None
            kind = kind if kind and kind != "rule" else "rule" if p.get("type") == "rule" else "rules"
            yield "rules", name, kind, rec(name, kind, lab("book", book), txt)


def table_lines(docs, ed):
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
            v = clean(resolve(r.get("description") or r.get("text") or "", Ctx(rules=ed))) or r.get("name") or (
                doc_by_uuid(r.get("documentUuid") or "") or {}).get("name", "")
            if r.get("name") and r.get("description") and r["name"] not in v:
                v = f"{r['name']}: {v}"
            res.append(f"{lo if lo == hi else f'{lo}-{hi}'}:{clean(v)}")
        res.sort(key=lambda x: int(re.match(r"\d+", x).group()) if re.match(r"\d+", x) else 0)
        yield t["name"], rec(t["name"], "table", lab("roll", t.get("formula")),
                             text_of(t.get("description"), Ctx(rules=ed)), "; ".join(res))


# ---------------------------------------------------------------- main

def item_file(pack, d):
    """Which output file an item from a pack belongs in."""
    t = d.get("type")
    if pack.startswith("monsterfeatures"):
        return "monster-features"
    if t == "spell":
        return "spells"
    if t == "class":
        return "classes"
    if t == "subclass":
        return "subclasses"
    if t == "race":
        return "species"
    if t == "background":
        return "backgrounds"
    if t == "feat":
        tv = g(d, "system", "type", "value") or ""
        return {"class": "class-features", "race": "species", "background": "backgrounds", "feat": "feats",
                "monster": "monster-features"}.get(tv, "feats" if pack.startswith("feats") else "class-features")
    if t in ("weapon", "equipment", "consumable", "tool", "loot", "container"):
        return "class-features" if pack.startswith("class") else "equipment"
    return None


FORMATTERS = {"spell": f_spell, "class": f_class, "subclass": f_subclass, "feat": f_feature, "race": f_species,
              "background": f_background}


def index_docs(db):
    for pack, docs in db.items():
        for k, d in docs.items():
            if not isinstance(d, dict) or "_id" not in d:
                continue
            m = re.match(r"!(\w+)(?:\.(\w+))?!(.*)", k)
            if not m:
                continue
            coll, sub, key = m.groups()
            if coll == "actors" and sub == "items":
                EMBEDDED.setdefault((pack, key.split(".")[0]), []).append(d)
                continue
            if sub and sub != "pages":
                continue
            d["_pack"] = pack
            DOCS.setdefault(d["_id"], d)
            PACK_DOCS[pack, d["_id"]] = d
    for pack, docs in db.items():
        for k, d in docs.items():
            if k.startswith("!journal.pages!") and d.get("type") == "rule":
                RULE_NAMES.setdefault(slug(d["name"]), d["name"])
            if k.startswith("!items!") and d.get("type") in ("class", "subclass"):
                ident = g(d, "system", "identifier") or slug(d["name"])
                label = d["name"] if d["type"] == "class" else (g(d, "system", "classIdentifier") or "").title()
                for a in advancements(d):
                    if a.get("type") == "ScaleValue":
                        sid = g(a, "configuration", "identifier") or re.sub(r"[^a-z0-9]+", "-", a.get("title", "")
                                                                             .lower()).strip("-")
                        SCALES.setdefault((EDITIONS[pack], f"{ident}.{sid}"), a)
                    if a.get("type") == "ItemGrant" and a.get("level") is not None:
                        for it in g(a, "configuration", "items", default=[]) or []:
                            doc = doc_by_uuid((it.get("uuid") if isinstance(it, dict) else it) or "")
                            if doc:
                                GRANTED.setdefault(doc["_id"], f"{d['name']} {a['level']}" if d["type"] == "subclass"
                                                   else f"{label} {a['level']}")


def check(out: Path) -> int:
    """Compare the installed tag in out/VERSION against the latest release. Returns 1 if outdated."""
    vf = out / "VERSION"
    have = vf.read_text(encoding="utf-8").split()[0] if vf.exists() and vf.read_text(encoding="utf-8").strip() else None
    new = latest_tag()
    print(f"dnd5e: installed {have or 'none'}, latest {new} ({'up to date' if have == new else 'update available'})")
    return 0 if have == new else 1


def main():
    ap = argparse.ArgumentParser(description=f"Extract the D&D 5e SRD from the {REPO} release zip.")
    ap.add_argument("--tag", metavar="TAG", help="release tag, e.g. release-6.0.5 or 6.0.5 (default: latest)")
    ap.add_argument("--out", default=Path(__file__).resolve().parent / "skill" / "dnd5e" / "data", type=Path,
                    help="output directory (default: skill/dnd5e/data next to this script)")
    ap.add_argument("--check", action="store_true", help="compare installed data with the latest release and exit")
    a = ap.parse_args()
    if a.check:
        sys.exit(check(a.out))
    tag = a.tag or latest_tag()
    tag = tag if tag.startswith("release-") else f"release-{tag}"
    files_in = open_packs(tag)
    db = {p: read_pack(files_in, p) for p in packs(files_in) if p in EDITIONS}
    unknown = [p for p in packs(files_in) if p not in EDITIONS and p not in ("heroes", "effects")]
    if unknown:
        print(f"warning: skipping unknown packs: {', '.join(unknown)}", file=sys.stderr)
    index_docs(db)
    # spell id -> {"class": {...}, "subclass": {...}} from the spell-list journal pages
    spell_classes = defaultdict(lambda: defaultdict(set))
    for d in PACK_DOCS.values():
        if d.get("type") == "spells" and "text" in d:
            owner = re.sub(r" (Spells|Spell List)$", "", d["name"])
            for uuid in g(d, "system", "spells", default=[]) or []:
                sd = doc_by_uuid(uuid)
                if sd:
                    spell_classes[sd["_id"]][g(d, "system", "type") or "class"].add(owner)
    extra = {"classes": spell_classes}
    files = defaultdict(list)
    index = defaultdict(list)
    stats = Counter()
    for pack, docs in db.items():
        ed = EDITION[0] = EDITIONS[pack]
        for fname, name, kind, line in journal_lines(docs, ed):
            files[ed, fname].append(line)
            index[ed].append(rec(name, kind, fname))
            stats[f"{ed} {kind if kind in ('spell list', 'rules') else 'rule'}"] += 1
        for name, line in table_lines(docs, ed):
            files[ed, "tables"].append(line)
            index[ed].append(rec(name, "table", "tables"))
            stats[f"{ed} table"] += 1
        for k, d in docs.items():
            if k.startswith("!actors!"):
                if d.get("type") == "npc":
                    files[ed, "monsters"].append(f_monster(d, ed, extra))
                    index[ed].append(rec(d["name"], "monster", "monsters"))
                    stats[f"{ed} monster"] += 1
                elif d.get("type") == "vehicle":
                    files[ed, "vehicles"].append(f_vehicle(d, ed, extra))
                    index[ed].append(rec(d["name"], "vehicle", "vehicles"))
                    stats[f"{ed} vehicle"] += 1
                continue
            if not k.startswith("!items!"):
                continue
            fname = item_file(pack, d)
            if not fname:
                stats[f"skipped:{d.get('type')}"] += 1
                continue
            fmt = FORMATTERS.get(d["type"], f_equipment)
            line = fmt(d, ed, extra)
            files[ed, fname].append(line)
            index[ed].append(rec(d["name"], line.split("|")[1], fname))
            stats[f"{ed} {line.split('|')[1]}"] += 1
    a.out.mkdir(parents=True, exist_ok=True)
    for old in a.out.glob("*/*.txt"):
        old.unlink()
    for (ed, fname), lines in files.items():
        (a.out / ed).mkdir(exist_ok=True)
        lines = sorted(set(lines), key=str.lower)
        (a.out / ed / f"{fname}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for ed, lines in index.items():
        (a.out / ed / "index.txt").write_text("\n".join(sorted(set(lines), key=str.lower)) + "\n", encoding="utf-8")
    (a.out / "VERSION").write_text(f"{tag} {asset_url(tag)}\n", encoding="utf-8")
    for k, v in sorted(stats.items()):
        print(f"{v:6} {k}")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
