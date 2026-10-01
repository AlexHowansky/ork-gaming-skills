#!/usr/bin/env python3
"""Discord bot: /pf looks up Pathfinder 2e and Starfinder 2e records.

  pfbot.py                      run the bot (needs DISCORD_TOKEN)
  pfbot.py --sync               also register slash commands with Discord (global, or PF_GUILD_ID)
  pfbot.py --preview QUERY      print what the bot would show, without connecting
  pfbot.py --verbose            log every interaction to the console
"""
import argparse
import asyncio
import logging
import os
import sys

import discord
from discord import app_commands

from store import Store, encode, kind_of, name_of
import render

log = logging.getLogger("pfbot")
TIMEOUT = 14 * 60  # interaction tokens expire after 15 minutes


def trunc(s, n=100):
    return s if len(s) <= n else s[: n - 1] + "…"


def embed(r, store, page=0):
    e = discord.Embed(title=trunc(r.name, 256), description=r.pages[page], color=render.COLORS.get(r.game))
    e.set_footer(text=render.footer(r, store, page))
    return e


def option(rec, value):
    return discord.SelectOption(label=trunc(name_of(rec)), value=value,
                                description=trunc(label(rec)))


def label(rec):
    """'PF2e spell 3 (spells)': tells apart same-named records across games and files."""
    return f"{render.GAME_TAGS.get(rec[0], rec[0])} {kind_of(rec)} ({rec[1]})"


def make_view(store, rec, choices, page=0, placeholder="Other matches"):
    """Buttons and dropdown for a shown record. `choices` are alternative records."""
    r = render.render(rec)

    class ResultView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=TIMEOUT)
            if choices:
                sel = discord.ui.Select(placeholder=placeholder, row=0,
                                        options=[option(c, str(i)) for i, c in enumerate(choices[:25])])
                sel.callback = self.pick
                self.add_item(sel)
            if len(r.pages) > 1:
                self.add_button("◀", discord.ButtonStyle.secondary, self.prev, page == 0)
                self.add_button("▶", discord.ButtonStyle.secondary, self.next, page == len(r.pages) - 1)
            if store.lore_for(rec):
                self.add_button("Lore", discord.ButtonStyle.secondary, self.lore)
            self.add_button("Share to channel", discord.ButtonStyle.primary, self.share)

        def add_button(self, label, style, cb, disabled=False):
            b = discord.ui.Button(label=label, style=style, disabled=disabled, row=1)
            b.callback = cb
            self.add_item(b)

        async def pick(self, interaction):
            chosen = choices[int(interaction.data["values"][0])]
            await show(interaction, store, chosen, choices, edit=True, placeholder=placeholder)

        async def prev(self, interaction):
            await self.turn(interaction, page - 1)

        async def next(self, interaction):
            await self.turn(interaction, page + 1)

        async def turn(self, interaction, p):
            await interaction.response.edit_message(
                embed=embed(r, store, p), view=make_view(store, rec, choices, p, placeholder))

        async def lore(self, interaction):
            await show(interaction, store, store.lore_for(rec), [])

        async def share(self, interaction):
            await interaction.response.send_message(embed=embed(r, store, page), ephemeral=False)

    return embed(r, store, page), ResultView()


async def show(interaction, store, rec, choices, edit=False, placeholder="Other matches"):
    e, view = make_view(store, rec, choices, placeholder=placeholder)
    if edit:
        await interaction.response.edit_message(embed=e, view=view)
    else:
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)


def search_embed(query, hits):
    desc = "Text matches:"
    for (g, stem, line), m in hits:
        s = max(0, m.start() - 50)
        snippet = render.esc(line[s:m.end() + 50].replace("|", " · "))
        entry = f"\n**{render.esc(name_of((g, stem, line)))}** ({render.GAME_TAGS[g]} {stem}): …{snippet}…"
        if len(desc) + len(entry) > render.PAGE:
            break
        desc += entry
    e = discord.Embed(title=trunc(f"No name matches “{query}”", 256), description=desc)
    e.set_footer(text="Pick one below")
    return e


async def lookup(interaction, store, query):
    hits = store.find(query)
    if hits:
        await show(interaction, store, hits[0], hits[:25] if len(hits) > 1 else [])
        return
    found = await asyncio.to_thread(store.search, query)
    if not found:
        await interaction.response.send_message(f"No match for “{render.esc(query)}”.", ephemeral=True)
        return
    recs = [rec for rec, _ in found]

    class SearchView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=TIMEOUT)
            sel = discord.ui.Select(placeholder="Open a result",
                                    options=[option(c, str(i)) for i, c in enumerate(recs)])
            sel.callback = self.pick
            self.add_item(sel)

        async def pick(self, inter):
            chosen = recs[int(inter.data["values"][0])]
            await show(inter, store, chosen, recs, edit=True, placeholder="Other text matches")

    await interaction.response.send_message(embed=search_embed(query, found), view=SearchView(),
                                            ephemeral=True)


def describe(interaction):
    """One-line summary of an interaction for --verbose, or None if it isn't ours."""
    data = interaction.data or {}
    opts = {o["name"]: o for o in data.get("options", [])}
    if interaction.type is discord.InteractionType.autocomplete and data.get("name") == "pf":
        what = f'autocomplete "{opts.get("query", {}).get("value", "")}"'
    elif interaction.type is discord.InteractionType.application_command and data.get("name") == "pf":
        what = f'/pf "{opts.get("query", {}).get("value", "")}"'
    elif interaction.type is discord.InteractionType.component:
        # Views use random custom ids, so name the component by what the message shows for it.
        comp = next((c for row in (interaction.message.components if interaction.message else [])
                     for c in getattr(row, "children", [row]) if c.custom_id == data.get("custom_id")), None)
        if "values" in data:
            value = data["values"][0] if data["values"] else ""
            chosen = next((o.label for o in getattr(comp, "options", []) if o.value == value), value)
            what = f"select → {chosen}"
        else:
            what = f"button {getattr(comp, 'label', None) or data.get('custom_id')}"
    else:
        return None
    where = f"guild {interaction.guild_id}" if interaction.guild_id else "DM"
    return f"{interaction.user} ({where}): {what}"


def build(store, verbose=False):
    client = discord.Client(intents=discord.Intents.default(), allowed_mentions=discord.AllowedMentions.none())
    tree = app_commands.CommandTree(client)

    if verbose:
        @client.event
        async def on_interaction(interaction):
            what = describe(interaction)
            if what:
                log.info("%s", what)

    @tree.command(name="pf", description="Look up a Pathfinder 2e or Starfinder 2e rule, spell, feat, creature, item…")
    @app_commands.describe(query="Name to look up (or text to search for)")
    async def pf(interaction: discord.Interaction, query: str):
        await lookup(interaction, store, query)

    @pf.autocomplete("query")
    async def complete(interaction: discord.Interaction, current: str):
        out = []
        for rec in store.suggest(current):
            value = encode(rec)
            if len(value) > 100:
                value = name_of(rec)[:100]
            out.append(app_commands.Choice(name=trunc(f"{name_of(rec)} — {label(rec)}"), value=value))
        return out

    @tree.error
    async def on_error(interaction, error):
        log.exception("command failed", exc_info=error)
        msg = "Something went wrong looking that up."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    return client, tree


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sync", action="store_true", help="register slash commands with Discord on startup")
    ap.add_argument("--preview", metavar="QUERY", help="print rendered result and exit")
    ap.add_argument("--verbose", action="store_true", help="log every interaction to the console")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    store = Store()

    if a.preview:
        query = a.preview
        hits = store.find(query)
        if not hits:
            found = store.search(query)
            for rec, m in found:
                print(f"[{rec[0]}/{rec[1]}] {name_of(rec)}")
            if not found:
                print(f"No match for “{query}”.")
            return
        print(render.to_text(render.render(hits[0]), store))
        if len(hits) > 1:
            print("\nOther matches: " + "; ".join(f"{name_of(h)} [{h[0]}/{h[1]}]" for h in hits[1:25]))
        lore = store.lore_for(hits[0])
        if lore:
            print("\n(has lore)")
        return

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        sys.exit("DISCORD_TOKEN is not set")
    client, tree = build(store, a.verbose)
    @client.event
    async def setup_hook():
        if a.sync:
            gid = os.environ.get("PF_GUILD_ID")
            if gid:
                guild = discord.Object(id=int(gid))
                tree.copy_global_to(guild=guild)
                synced = await tree.sync(guild=guild)
            else:
                synced = await tree.sync()
            log.info("synced %d commands%s", len(synced), f" to guild {gid}" if gid else " globally")

    @client.event
    async def on_ready():
        log.info("logged in as %s; data %s", client.user, store.version)

    client.run(token, log_handler=None)


if __name__ == "__main__":
    main()
