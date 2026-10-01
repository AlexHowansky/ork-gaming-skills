#!/usr/bin/env python3
"""Discord bot: /pf and /sf look up Pathfinder 2e / Starfinder 2e records.

  pfbot.py                      run the bot (needs DISCORD_TOKEN)
  pfbot.py --sync               also register slash commands with Discord (global, or PF_GUILD_ID)
  pfbot.py --preview GAME QUERY print what the bot would show, without connecting
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
                                description=trunc(f"{kind_of(rec)} ({rec[1]})"))


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


def search_embed(game, query, hits):
    desc = "Text matches:"
    for (g, stem, line), m in hits:
        s = max(0, m.start() - 50)
        snippet = render.esc(line[s:m.end() + 50].replace("|", " · "))
        entry = f"\n**{render.esc(name_of((g, stem, line)))}** ({stem}): …{snippet}…"
        if len(desc) + len(entry) > render.PAGE:
            break
        desc += entry
    e = discord.Embed(title=trunc(f"No name matches “{query}”", 256), description=desc,
                      color=render.COLORS.get(game))
    e.set_footer(text=render.GAME_NAMES[game] + " · pick one below")
    return e


async def lookup(interaction, store, game, query):
    hits = store.find(game, query)
    if hits:
        await show(interaction, store, hits[0], hits[:25] if len(hits) > 1 else [])
        return
    found = await asyncio.to_thread(store.search, game, query)
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

    await interaction.response.send_message(embed=search_embed(game, query, found), view=SearchView(),
                                            ephemeral=True)


def build(store):
    client = discord.Client(intents=discord.Intents.default(), allowed_mentions=discord.AllowedMentions.none())
    tree = app_commands.CommandTree(client)

    def choices(game, current):
        out = []
        for rec in store.suggest(game, current):
            value = encode(rec)
            if len(value) > 100:
                value = name_of(rec)[:100]
            out.append(app_commands.Choice(name=trunc(f"{name_of(rec)} — {kind_of(rec)} ({rec[1]})"), value=value))
        return out

    def register(game, cmd, desc):
        @tree.command(name=cmd, description=f"Look up a {desc} rule, spell, feat, creature, item…")
        @app_commands.describe(query="Name to look up (or text to search for)")
        async def callback(interaction: discord.Interaction, query: str):
            await lookup(interaction, store, game, query)

        @callback.autocomplete("query")
        async def complete(interaction: discord.Interaction, current: str):
            return choices(game, current)

    register("pf2e", "pf", "Pathfinder 2e")
    register("sf2e", "sf", "Starfinder 2e")

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
    ap.add_argument("--preview", nargs=2, metavar=("GAME", "QUERY"), help="print rendered result and exit")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    store = Store()

    if a.preview:
        game, query = a.preview
        hits = store.find(game, query)
        if not hits:
            found = store.search(game, query)
            for (g, stem, line), m in found:
                print(f"[{stem}] {name_of((g, stem, line))}")
            if not found:
                print(f"No match for “{query}”.")
            return
        print(render.to_text(render.render(hits[0]), store))
        if len(hits) > 1:
            print("\nOther matches: " + "; ".join(name_of(h) for h in hits[1:25]))
        lore = store.lore_for(hits[0])
        if lore:
            print("\n(has lore)")
        return

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        sys.exit("DISCORD_TOKEN is not set")
    client, tree = build(store)
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
