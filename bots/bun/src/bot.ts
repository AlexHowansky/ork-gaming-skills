/**
 * Discord bot: /pf looks up Pathfinder 2e and Starfinder 2e records. A port of bots/python/pfbot.py.
 *
 *   bun src/bot.ts                  run the bot (needs DISCORD_TOKEN)
 *   bun src/bot.ts --sync           also register slash commands with Discord (global, or PF_GUILD_ID)
 *   bun src/bot.ts --preview QUERY  print what the bot would show, without connecting
 *   bun src/bot.ts --verbose        log every interaction and gateway event to the console
 */
import {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  Client,
  EmbedBuilder,
  Events,
  GatewayIntentBits,
  MessageFlags,
  SlashCommandBuilder,
  StringSelectMenuBuilder,
  StringSelectMenuOptionBuilder,
  type AutocompleteInteraction,
  type ButtonInteraction,
  type ChatInputCommandInteraction,
  type Interaction,
  type InteractionReplyOptions,
  type StringSelectMenuInteraction,
} from "discord.js";
import * as render from "./render";
import { encode, kindOf, nameOf, Store, type Hit, type Rec } from "./store";

const TTL = 14 * 60 * 1000; // interaction tokens expire after 15 minutes
const PREFIX = "pf";

/**
 * What a result message is showing. discord.js has no per-message view objects, so buttons and
 * dropdowns carry `pf:<action>:<state id>` and look their state up here.
 */
type State = { rec: Rec | null; choices: Rec[]; page: number; placeholder: string; expires: number };
const states = new Map<string, State>();

function remember(state: Omit<State, "expires">): string {
  const id = crypto.randomUUID().slice(0, 8);
  states.set(id, { ...state, expires: Date.now() + TTL });
  return id;
}

function sweep() {
  const now = Date.now();
  for (const [id, s] of states) if (s.expires < now) states.delete(id);
}

function trunc(s: string, n = 100): string {
  return s.length <= n ? s : s.slice(0, n - 1) + "…";
}

/** 'PF2e spell 3 (spells)': tells apart same-named records across games and files. */
function label(rec: Rec): string {
  return `${render.GAME_TAGS[rec[0]] ?? rec[0]} ${kindOf(rec)} (${rec[1]})`;
}

function embed(r: render.Rendered, store: Store, page = 0): EmbedBuilder {
  return new EmbedBuilder()
    .setTitle(trunc(r.name, 256))
    .setDescription(r.pages[page]!)
    .setColor(render.COLORS[r.game] ?? null)
    .setFooter({ text: render.footer(r, store.sources, page) });
}

function select(id: string, placeholder: string, choices: Rec[]) {
  return new ActionRowBuilder<StringSelectMenuBuilder>().addComponents(
    new StringSelectMenuBuilder()
      .setCustomId(`${PREFIX}:pick:${id}`)
      .setPlaceholder(placeholder)
      .addOptions(
        choices.slice(0, 25).map((c, i) =>
          new StringSelectMenuOptionBuilder().setLabel(trunc(nameOf(c))).setValue(String(i)).setDescription(trunc(label(c))),
        ),
      ),
  );
}

/** Embed and components for a record message described by `state` (stored under `id`). */
function view(store: Store, id: string, state: State) {
  const rec = state.rec!;
  const r = render.render(rec);
  const page = Math.min(state.page, r.pages.length - 1);
  const components: ActionRowBuilder<any>[] = [];
  if (state.choices.length) components.push(select(id, state.placeholder, state.choices));
  const button = (action: string, text: string, style = ButtonStyle.Secondary, disabled = false) =>
    new ButtonBuilder().setCustomId(`${PREFIX}:${action}:${id}`).setLabel(text).setStyle(style).setDisabled(disabled);
  const buttons: ButtonBuilder[] = [];
  if (r.pages.length > 1) {
    buttons.push(button("prev", "◀", ButtonStyle.Secondary, page === 0));
    buttons.push(button("next", "▶", ButtonStyle.Secondary, page === r.pages.length - 1));
  }
  if (store.loreFor(rec)) buttons.push(button("lore", "Lore"));
  buttons.push(button("share", "Share to channel", ButtonStyle.Primary));
  components.push(new ActionRowBuilder<ButtonBuilder>().addComponents(buttons));
  return { embeds: [embed(r, store, page)], components };
}

/** A new private message showing `rec`, with `choices` in the dropdown. */
function showNew(store: Store, rec: Rec, choices: Rec[], placeholder = "Other matches"): InteractionReplyOptions {
  const id = remember({ rec, choices, page: 0, placeholder });
  return { ...view(store, id, states.get(id)!), flags: MessageFlags.Ephemeral };
}

function searchEmbed(query: string, hits: Hit[]): EmbedBuilder {
  let desc = "Text matches:";
  for (const { rec, start, end } of hits) {
    const line = rec[2];
    const snippet = render.esc(line.slice(Math.max(0, start - 50), end + 50).replaceAll("|", " · "));
    const entry = `\n**${render.esc(nameOf(rec))}** (${render.GAME_TAGS[rec[0]]} ${rec[1]}): …${snippet}…`;
    if (desc.length + entry.length > render.PAGE) break;
    desc += entry;
  }
  return new EmbedBuilder()
    .setTitle(trunc(`No name matches “${query}”`, 256))
    .setDescription(desc)
    .setFooter({ text: "Pick one below" });
}

export async function lookup(interaction: ChatInputCommandInteraction, store: Store) {
  const query = interaction.options.getString("query", true);
  const hits = store.find(query);
  if (hits.length) {
    await interaction.reply(showNew(store, hits[0]!, hits.length > 1 ? hits.slice(0, 25) : []));
    return;
  }
  const found = store.search(query);
  if (!found.length) {
    await interaction.reply({ content: `No match for “${render.esc(query)}”.`, flags: MessageFlags.Ephemeral });
    return;
  }
  const recs = found.map((h) => h.rec);
  const id = remember({ rec: null, choices: recs, page: 0, placeholder: "Other text matches" });
  await interaction.reply({
    embeds: [searchEmbed(query, found)],
    components: [select(id, "Open a result", recs)],
    flags: MessageFlags.Ephemeral,
  });
}

export async function complete(interaction: AutocompleteInteraction, store: Store) {
  const current = interaction.options.getFocused();
  await interaction.respond(
    store.suggest(current).map((rec) => {
      let value = encode(rec);
      if (value.length > 100) value = nameOf(rec).slice(0, 100);
      return { name: trunc(`${nameOf(rec)} — ${label(rec)}`), value };
    }),
  );
}

export async function component(interaction: ButtonInteraction | StringSelectMenuInteraction, store: Store) {
  const [, action, id] = interaction.customId.split(":");
  const state = id ? states.get(id) : undefined;
  if (!state || state.expires < Date.now()) {
    await interaction.reply({ content: "This result expired — run /pf again.", flags: MessageFlags.Ephemeral });
    return;
  }
  state.expires = Date.now() + TTL;
  switch (action) {
    case "pick": {
      const chosen = state.choices[Number((interaction as StringSelectMenuInteraction).values[0])];
      if (!chosen) return;
      state.rec = chosen;
      state.page = 0;
      await interaction.update(view(store, id!, state));
      return;
    }
    case "prev":
    case "next":
      state.page += action === "next" ? 1 : -1;
      await interaction.update(view(store, id!, state));
      return;
    case "lore": {
      const lore = state.rec && store.loreFor(state.rec);
      if (lore) await interaction.reply(showNew(store, lore, []));
      return;
    }
    case "share":
      if (state.rec) await interaction.reply({ embeds: [embed(render.render(state.rec), store, state.page)] });
      return;
  }
}

export const command = new SlashCommandBuilder()
  .setName("pf")
  .setDescription("Look up a Pathfinder 2e or Starfinder 2e rule, spell, feat, creature, item…")
  .addStringOption((o) =>
    o.setName("query").setDescription("Name to look up (or text to search for)").setRequired(true).setAutocomplete(true),
  );

/** One-line summary of an interaction for --verbose, or null if it isn't ours. */
export function describe(interaction: Interaction): string | null {
  let what: string;
  if (interaction.isAutocomplete() && interaction.commandName === "pf")
    what = `autocomplete ${JSON.stringify(interaction.options.getFocused())}`;
  else if (interaction.isChatInputCommand() && interaction.commandName === "pf")
    what = `/pf ${JSON.stringify(interaction.options.getString("query") ?? "")}`;
  else if ((interaction.isButton() || interaction.isStringSelectMenu()) && interaction.customId.startsWith(`${PREFIX}:`)) {
    const [, action, id] = interaction.customId.split(":");
    if (interaction.isButton()) what = `button ${action}`;
    else {
      const value = interaction.values[0] ?? "";
      const chosen = id ? states.get(id)?.choices[Number(value)] : undefined;
      what = `select ${action} → ${chosen ? nameOf(chosen) : value}`;
    }
  } else return null;
  const where = interaction.guildId ? `guild ${interaction.guildId}` : "DM";
  return `${interaction.user.tag} (${where}): ${what}`;
}

const stamp = () => new Date().toISOString();

export function build(store: Store, verbose = false): Client {
  const client = new Client({ intents: [GatewayIntentBits.Guilds], allowedMentions: { parse: [] } });
  if (verbose) {
    client.on(Events.Warn, (msg) => console.log(`${stamp()} warn: ${msg}`));
    client.on(Events.ShardDisconnect, (event, shard) => console.log(`${stamp()} shard ${shard} disconnected (${event.code})`));
    client.on(Events.ShardReconnecting, (shard) => console.log(`${stamp()} shard ${shard} reconnecting`));
    client.on(Events.ShardResume, (shard, replayed) => console.log(`${stamp()} shard ${shard} resumed (${replayed} events replayed)`));
    client.on(Events.ShardError, (error, shard) => console.log(`${stamp()} shard ${shard} error: ${error.message}`));
  }
  client.on(Events.InteractionCreate, async (interaction: Interaction) => {
    // Describe before dispatch: picking from a dropdown changes the state it reads.
    const what = verbose ? describe(interaction) : null;
    const start = performance.now();
    try {
      if (interaction.isAutocomplete() && interaction.commandName === "pf") await complete(interaction, store);
      else if (interaction.isChatInputCommand() && interaction.commandName === "pf") await lookup(interaction, store);
      else if ((interaction.isButton() || interaction.isStringSelectMenu()) && interaction.customId.startsWith(`${PREFIX}:`))
        await component(interaction, store);
    } catch (error) {
      console.error("command failed", error);
      if (!interaction.isRepliable()) return;
      const msg = { content: "Something went wrong looking that up.", flags: MessageFlags.Ephemeral } as const;
      try {
        if (interaction.replied || interaction.deferred) await interaction.followUp(msg);
        else await interaction.reply(msg);
      } catch {}
    } finally {
      if (what) console.log(`${stamp()} ${what} [${Math.round(performance.now() - start)} ms]`);
    }
  });
  return client;
}

async function main() {
  const args = Bun.argv.slice(2);
  const store = await Store.load();

  const p = args.indexOf("--preview");
  if (p >= 0) {
    const query = args[p + 1] ?? "";
    const hits = store.find(query);
    if (!hits.length) {
      const found = store.search(query);
      for (const { rec } of found) console.log(`[${rec[0]}/${rec[1]}] ${nameOf(rec)}`);
      if (!found.length) console.log(`No match for “${query}”.`);
      return;
    }
    console.log(render.toText(render.render(hits[0]!), store.sources));
    if (hits.length > 1)
      console.log("\nOther matches: " + hits.slice(1, 25).map((h) => `${nameOf(h)} [${h[0]}/${h[1]}]`).join("; "));
    if (store.loreFor(hits[0]!)) console.log("\n(has lore)");
    return;
  }

  const token = process.env.DISCORD_TOKEN;
  if (!token) {
    console.error("DISCORD_TOKEN is not set");
    process.exit(1);
  }
  const client = build(store, args.includes("--verbose"));
  client.once(Events.ClientReady, async (c) => {
    console.log(`logged in as ${c.user.tag}; data ${JSON.stringify(Object.fromEntries(store.version))}`);
    if (args.includes("--sync")) {
      const gid = process.env.PF_GUILD_ID;
      const synced = gid
        ? await c.application.commands.set([command.toJSON()], gid)
        : await c.application.commands.set([command.toJSON()]);
      console.log(`synced ${synced.size} commands${gid ? ` to guild ${gid}` : " globally"}`);
    }
  });
  setInterval(sweep, 60_000);
  await client.login(token);
}

if (import.meta.main) await main();
