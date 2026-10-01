"""Turn a compact record line into Discord markdown pages.

Record format (see skill/pf2e-rules/SKILL.md):
  Name|kind level|SRC [R]|label:value|...|description
"""
import re
from dataclasses import dataclass, field

PAGE = 4000  # embed description limit is 4096
COLORS = {"pf2e": 0x5D0000, "sf2e": 0x1F6FB2}
GAME_NAMES = {"pf2e": "Pathfinder 2e", "sf2e": "Starfinder 2e"}

ACTIONS = {"1a": "◆", "2a": "◆◆", "3a": "◆◆◆", "r": "⟲", "f": "◇", "0": "◇"}
LETTER_ACTIONS = {"A": "◆", "D": "◆◆", "T": "◆◆◆", "R": "⟲", "F": "◇"}

LABELS = {
    "tr": "Traits", "act": "Actions", "cast": "Cast", "trad": "Traditions",
    "rng": "Range", "area": "Area", "tgt": "Targets", "def": "Defense", "dur": "Duration",
    "prereq": "Prerequisites", "req": "Requirements", "trig": "Trigger", "freq": "Frequency",
    "price": "Price", "bulk": "Bulk", "usage": "Usage", "cat": "Category", "dmg": "Damage",
    "dexcap": "Dex Cap", "chk": "Check Penalty", "spd": "Speed", "str": "Strength",
    "hard": "Hardness", "hp": "HP", "perc": "Perception", "lang": "Languages",
    "skills": "Skills", "imm": "Immunities", "weak": "Weaknesses", "res": "Resistances",
    "gear": "Items", "ab": "", "spells": "Spells", "stealth": "Stealth", "disable": "Disable",
    "routine": "Routine", "reset": "Reset", "desc": "Description", "blurb": "",
    "key": "Key Attribute", "saves": "Saves", "atk": "Attacks", "features": "Features",
    "boost": "Attribute Boosts", "flaw": "Attribute Flaw", "anc": "Ancestry",
    "sanct": "Sanctification", "font": "Divine Font", "attr": "Divine Attribute",
    "skill": "Divine Skill", "weapon": "Favored Weapon", "dom": "Domains",
    "altdom": "Alternate Domains", "reload": "Reload", "ac": "AC", "crew": "Crew",
    "passengers": "Passengers", "uses": "Uses", "level": "Level", "size": "Size",
    "vision": "Vision", "speed": "Speed", "cost": "Cost", "ritual": "Ritual",
    "feat": "Feat", "feats": "Feats", "spellcasting": "Spellcasting",
}
HIDDEN = {"pack"}
SIZES = {"tiny": "Tiny", "sm": "Small", "med": "Medium", "lg": "Large", "huge": "Huge", "garg": "Gargantuan"}
RANKS = {"C": "Cantrips", "1": "1st", "2": "2nd", "3": "3rd"}
ATTRS = ("str", "dex", "con", "int", "wis", "cha")

SRC_RE = re.compile(r"^([^\s:|]+)( R)?$")
LABEL_RE = re.compile(r"^([a-z]{1,12}):(.*)$", re.S)
ATTR_RE = re.compile(r"^(?:(?:cha|con|dex|int|str|wis)[+-]\d+ ?)+$")
KEYWORD_RE = re.compile(
    r"^(Critical Success|Critical Failure|Success|Failure|Trigger|Requirements?|Effect|Frequency"
    r"|Saving Throw|Maximum Duration|Onset|Stage \d+|Heightened \([^)]*\)|Activate|Craft Requirements"
    r"|Special|Cost|Access|Amp(?: Heightened \([^)]*\))?|Prerequisites|Religious Symbol"
    r"|Sacred Animal|Sacred Colors|Areas|Edicts|Anathema|Follower Alignments)(?=[\s:]|$):?"
)


@dataclass
class Rendered:
    game: str
    stem: str
    name: str
    kind: str
    source: str = ""
    remaster: bool = False
    pages: list = field(default_factory=list)


def glyph(code):
    return ACTIONS.get(code, code)


def glyphs(text):
    """Replace [1a]/[r]/... tokens and 'Activate A' style Foundry letters with action glyphs."""
    text = re.sub(r"\[(1a|2a|3a|r|f|0)\]", lambda m: ACTIONS[m.group(1)], text)
    return re.sub(r"\bActivate ([ADTRF])\b", lambda m: "Activate " + LETTER_ACTIONS[m.group(1)], text)


def esc(text):
    """Escape characters Discord would treat as markdown; the data has no markdown of its own."""
    return re.sub(r"([\\*_~`|>])", r"\\\1", text.replace("¦", "|"))


def traits(value):
    out = []
    for t in value.split(","):
        t = SIZES.get(t, t)
        out.append(f"`{t.upper()}`")
    return " ".join(out)


def ordinal(r):
    if r in RANKS:
        return RANKS[r]
    return f"{r}th" if r.isdigit() else r


def spells(value):
    """'Arcane Innate Spells DC35 atk+27: 4 Suggestion; C Detect Magic' -> readable lines."""
    lines = []
    for entry in value.split(" // "):
        head, sep, body = entry.partition(": ")
        if not sep:
            lines.append(esc(entry))
            continue
        m = re.match(r"^(.*?)((?: DC\d+)?(?: atk[+-]\d+)?)$", head)
        title, stats = m.group(1), m.group(2)
        stats = re.sub(r"DC(\d+)", r"DC \1", stats)
        stats = re.sub(r"atk([+-]\d+)", r"attack \1", stats).strip()
        ranks = []
        for chunk in body.split("; "):
            rank, _, names = chunk.partition(" ")
            if re.fullmatch(r"C|\d+", rank):
                ranks.append(f"**{ordinal(rank)}** {esc(names.replace(',', ', '))}")
            else:
                ranks.append(esc(chunk))
        lines.append(f"**{esc(title)}** {stats}; " + "; ".join(ranks))
    return "\n".join(lines)


def ability(value):
    """'Name [2a] (traits) text / more' -> bold name, glyph, italic traits, paragraphs."""
    m = re.match(r"^(.+?) (\[(?:1a|2a|3a|r|f|0)\])(?: \(([^)]*)\))?(?: (.*))?$", value, re.S)
    if not m:
        m2 = re.match(r"^([^()]+?) \(([^)]*)\)(?: (.*))?$", value, re.S)
        if m2 and len(m2.group(1)) <= 40:
            name, act, tr, rest = m2.group(1), "", m2.group(2), m2.group(3) or ""
        else:
            return "• " + paragraphs(value)
    else:
        name, act, tr, rest = m.group(1), glyphs(m.group(2)), m.group(3), m.group(4) or ""
    head = f"• **{esc(name)}**"
    if act:
        head += f" {act}"
    if tr:
        head += f" ({esc(tr.replace(',', ', '))})"
    return head + (" " + paragraphs(rest) if rest else "")


def defenses(value):
    v = esc(value)
    v = re.sub(r"^AC(\d+)", r"**AC** \1", v)
    v = re.sub(r"\bF([+-]\d+)", r"**Fort** \1", v)
    v = re.sub(r"\bR([+-]\d+)", r"**Ref** \1", v)
    v = re.sub(r"\bW([+-]\d+)", r"**Will** \1", v)
    v = re.sub(r"\bhard(\d+)", r"**Hardness** \1", v)
    v = re.sub(r"\bHP(\d+)", r"**HP** \1", v)
    return v


def attributes(value):
    mods = dict(re.findall(r"(cha|con|dex|int|str|wis)([+-]\d+)", value))
    return " ".join(f"**{a.capitalize()}** {mods[a]}" for a in ATTRS if a in mods)


def strike(value):
    kind, _, rest = value.partition(" ")
    rest = glyphs(esc(rest))
    rest = re.sub(r"\brng(\d+)", r"range \1 ft.", rest)
    rest = re.sub(r"\(([^)]*)\)", lambda m: "(" + m.group(1).replace(",", ", ") + ")", rest, count=1)
    return f"**{kind.capitalize()}** {rest}"


def is_table(par):
    rows = par.split("; ")
    if len(rows) < 3:
        return False
    head = rows[:3]
    return all("," in r and len(r) < 60 and ". " not in r for r in head)


def table(par):
    rows = [r.split(",") for r in par.split("; ")]
    cells = [r for r in rows if len(r) > 1]
    width = max(len(r) for r in cells)
    widths = [max((len(r[i]) for r in cells if i < len(r)), default=0) for i in range(width)]
    out = []
    for r in rows:
        if len(r) == 1:
            out.append(r[0])
        else:
            out.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip())
    body = "\n".join(out).replace("`", "'").replace("¦", "|")
    return f"```\n{body}\n```"


def paragraph(par):
    par = par.strip()
    if not par:
        return ""
    m = re.fullmatch(r"\[([^\]]+)\]", par)
    if m:
        return f"__**{esc(m.group(1))}**__"
    if is_table(par):
        return table(par)
    text = glyphs(esc(par))
    k = KEYWORD_RE.match(text)
    if k:
        text = f"**{k.group(0).rstrip(':')}**" + text[k.end():]
    return text


def paragraphs(text):
    text = re.sub(r"\s*/\[([^\]]+)\]/\s*", r" / [\1] / ", text)
    return "\n".join(p for p in (paragraph(x) for x in text.split(" / ")) if p)


def field_line(label, value):
    if label == "tr":
        return traits(value)
    if label in ("act", "cast"):
        name = LABELS[label]
        return f"**{name}** {glyph(value)}"
    if label == "spells" and (" DC" in value or ": " in value):
        return spells(value)
    if label == "ab":
        return ability(value)
    if label == "blurb":
        return f"*{esc(value)}*"
    name = LABELS.get(label, label.capitalize())
    v = value
    if label in ("perc", "skills", "lang", "imm", "weak", "res", "spd", "gear", "trad", "dom", "altdom", "attr"):
        v = v.replace(",", ", ")
    if label == "features":
        return f"**{name}**\n" + "\n".join(esc(f) for f in v.split("; "))
    return f"**{name}** {paragraphs(v)}"


def parse(rec):
    game, stem, line = rec
    parts = line.split("|")
    r = Rendered(game=game, stem=stem, name=parts[0].replace("¦", "|"),
                 kind=parts[1] if len(parts) > 1 else "")
    rest = parts[2:]
    if len(rest) > 1 and SRC_RE.match(rest[0]):
        m = SRC_RE.match(rest[0])
        r.source, r.remaster = m.group(1), bool(m.group(2))
        rest = rest[1:]
    return r, rest


def blocks(rest):
    """Markdown blocks for the fields, grouped so related lines stay together."""
    out = []
    for p in rest:
        m = LABEL_RE.match(p)
        if m and (m.group(1) in LABELS or m.group(1) in HIDDEN or len(m.group(2)) < 200):
            label, value = m.group(1), m.group(2)
            if label in HIDDEN:
                continue
            out.append(field_line(label, value))
        elif ATTR_RE.match(p):
            out.append(attributes(p))
        elif re.match(r"^(AC|HP)\d", p):
            out.append(defenses(p))
        elif re.match(r"^(melee|ranged) ", p):
            out.append(strike(p))
        else:
            out.append(paragraphs(p))
    return out


def paginate(chunks, size=PAGE):
    """Pack lines into pages of at most `size` characters, splitting overlong lines on words."""
    pages, cur = [], ""
    lines = []
    for c in chunks:
        lines.extend(c.split("\n"))
    for line in lines:
        while len(line) > size:
            cut = line.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            pieces, line = line[:cut], line[cut:].lstrip()
            if cur:
                pages.append(cur)
                cur = ""
            pages.append(pieces)
        if len(cur) + len(line) + 1 > size:
            pages.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        pages.append(cur)
    return _fix_code_blocks(pages) or [""]


def _fix_code_blocks(pages):
    """Close and reopen ``` fences that a page break split."""
    out, carry = [], False
    for p in pages:
        if carry:
            p = "```\n" + p
        carry = p.count("```") % 2 == 1
        if carry:
            p += "\n```"
        out.append(p)
    return out


def render(rec):
    r, rest = parse(rec)
    header = f"*{esc(r.kind[:1].upper() + r.kind[1:])}*" if r.kind else ""
    rest = sorted(rest, key=lambda p: not p.startswith("tr:"))  # traits first; stable otherwise
    body = blocks(rest)
    r.pages = paginate(([header] if header else []) + body)
    return r


def footer(r, store=None, page=0):
    bits = [GAME_NAMES.get(r.game, r.game)]
    if r.source:
        title = store.sources.get(r.source) if store else None
        bits.append(f"{title} ({r.source})" if title else r.source)
    if r.remaster:
        bits.append("Remaster")
    if len(r.pages) > 1:
        bits.append(f"Page {page + 1}/{len(r.pages)}")
    return " · ".join(bits)


def to_text(r, store=None):
    """Plain preview of every page, for the --preview CLI."""
    out = []
    for i, p in enumerate(r.pages):
        out.append(f"=== {r.name} [{r.game}/{r.stem}] ===\n{p}\n--- {footer(r, store, i)}")
    return "\n\n".join(out)
