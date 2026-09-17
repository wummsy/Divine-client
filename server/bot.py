"""Divine Client Discord bot.

Runs alongside the website (app.py) as a separate process on the SAME server,
sharing the same SQLite database (server/data/divine.db). Because the DB is in WAL mode
the bot and the web app can both read and write it safely at the same time.

Features:
  * /link          - shows the user the launcher link page so they can connect
  * /friends       - lists the Divine friends of whoever runs the command
  * /addfriend     - send an Divine friend request to another Discord user
  * /getcode       - get the client hardware device code for a player by name, ID, or @mention
  * /code          - lookup Divine client device code and moderation records
  * /lookup        - full player profile, device code, and ban status lookup
  * /setchannel    - set channel for live in-game & launcher global chat logs
  * /setlogchannel - set channel for player connection & hardware device code audit logs
  * /ban           - ban a user or client device code (hardware ban) from Divine Client
  * /unban         - unban a device code or user
  * /banlist       - view all active banned client devices and users
  * /announce      - post an Divine Client update / announcement
  * Live Chat & Audit Relays: Forwards global chat and player connection events in real-time.

Setup (environment variables):
    DISCORD_BOT_TOKEN            the bot token from Discord Developer Portal
    DISCORD_CHAT_LOG_CHANNEL_ID  optional ID of the private chat log channel
    PUBLIC_BASE_URL              https://divineclient.wispbyte.org
    DIVINE_DB                      optional path to the shared db (defaults to data/divine.db)
"""
import asyncio
import os
import sys
import time

import envfile  # loads .env into os.environ before anything reads it

# Ensure root path is accessible for divineclient modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from divineclient.core import ingame_bridge
except Exception:
    ingame_bridge = None

import discord
from discord import app_commands
from discord.ext import tasks

import db

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://divineclient.wispbyte.org").rstrip("/")
DISCORD_INVITE_URL = os.environ.get("DISCORD_INVITE_URL", "https://discord.gg/ER2haQtach")
CHAT_LOG_CHANNEL_ID = os.environ.get("DISCORD_CHAT_LOG_CHANNEL_ID", "")

TEAL = 0x38E1D0
RED = 0xFF4D4D
GOLD = 0xF59E0B


def _display_name(user):
    return getattr(user, "global_name", None) or user.name


def _avatar(user):
    try:
        return str(user.display_avatar.url)
    except Exception:
        return ""


def _remember(user):
    """Make sure this Discord user exists in the shared DB."""
    db.upsert_user(str(user.id), _display_name(user), _avatar(user))


class DivineBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.last_logged_msg_id = 0
        self.last_logged_conn_id = 0

    async def setup_hook(self):
        db.init_db()
        # Initialize last message id so we don't spam historical messages on boot
        try:
            recent = db.room_messages(limit=1)
            if recent:
                self.last_logged_msg_id = recent[-1]["id"]
        except Exception:
            self.last_logged_msg_id = 0

        # Initialize last connection log id
        try:
            recent_conns = db.get_connection_logs(limit=1)
            if recent_conns:
                self.last_logged_conn_id = recent_conns[-1]["id"]
        except Exception:
            self.last_logged_conn_id = 0

        self.chat_logger_loop.start()
        self.audit_logger_loop.start()

    @tasks.loop(seconds=2.0)
    async def chat_logger_loop(self):
        """Polls for new room messages and relays them to the private Discord channel."""
        try:
            msgs = db.room_messages(since=self.last_logged_msg_id, limit=50)
            if not msgs:
                return

            channel = await self._get_chat_channel()
            if not channel:
                return

            for m in msgs:
                self.last_logged_msg_id = max(self.last_logged_msg_id, m["id"])
                sender = m.get("from") or "Unknown"
                text = m.get("text") or ""
                ts = int(m.get("ts") or time.time())
                
                embed = discord.Embed(
                    description=text,
                    color=TEAL,
                    timestamp=discord.utils.utcnow()
                )
                embed.set_author(name=f" {sender} (Divine Global Chat)")
                embed.set_footer(text=f"Message ID #{m['id']}")
                await channel.send(embed=embed)
        except Exception:
            pass

    @tasks.loop(seconds=2.0)
    async def audit_logger_loop(self):
        """Polls for new connection/link events and relays player device codes."""
        try:
            events = db.get_connection_logs(since=self.last_logged_conn_id, limit=50)
            if not events:
                return

            channel = await self._get_audit_channel()
            if not channel:
                return

            for ev in events:
                self.last_logged_conn_id = max(self.last_logged_conn_id, ev["id"])
                uid = ev.get("user_id") or ""
                uname = ev.get("username") or "Player"
                dcode = ev.get("device_code") or "DEV-UNKNOWN"
                etype = ev.get("event_type") or "login"
                ts = ev.get("created") or time.time()

                # Check if device or user is banned
                ban_row = db.is_banned(device_code=dcode, user_id=uid)
                is_banned = ban_row is not None

                if is_banned:
                    embed = discord.Embed(
                        title=" Banned Device Connection Attempt",
                        description=f"A banned hardware device attempted connection to Divine network.",
                        color=RED,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="Hardware Device Code", value=f"`{dcode}`", inline=False)
                    if uid:
                        embed.add_field(name="Discord Account", value=f"<@{uid}> (`{uname}` • ID: `{uid}`)", inline=True)
                    embed.add_field(name="Ban Reason", value=f"*{ban_row.get('reason', 'Violation of Terms of Service')}*", inline=False)
                    embed.set_footer(text=f"Log Event #{ev['id']}")
                    await channel.send(embed=embed)
                    continue

                if etype.startswith("code_redeemed:"):
                    parts = etype.split(":", 2)
                    prod = parts[1] if len(parts) > 1 else "Unknown"
                    rcode = parts[2] if len(parts) > 2 else "AREV-XXXX"
                    embed = discord.Embed(
                        title=" Product Code Redeemed",
                        description=f"**<@{uid}>** (`{uname}`) successfully claimed product **`{prod}`**.",
                        color=TEAL,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="Redeemed Code", value=f"**`{rcode}`**", inline=True)
                    embed.add_field(name="Product ID", value=f"`{prod}`", inline=True)
                    embed.add_field(name="User", value=f"<@{uid}> (`{uname}` • ID: `{uid}`)", inline=False)
                    embed.add_field(name="Device Code", value=f"`{dcode}`", inline=True)
                    embed.set_footer(text=f"Audit Event #{ev['id']} • Code Claimed")
                    await channel.send(embed=embed)
                elif etype == "link":
                    embed = discord.Embed(
                        title=" Discord Account Linked to Client",
                        description=f"**<@{uid}>** (`{uname}`) linked their Discord account to Divine Client.",
                        color=TEAL,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="User", value=f"<@{uid}> (`{uname}` • ID: `{uid}`)", inline=True)
                    embed.add_field(name="Hardware Device Code", value=f"**`{dcode}`**", inline=True)
                    embed.set_footer(text=f"Log Event #{ev['id']} • Account Linked")
                    await channel.send(embed=embed)
                elif etype == "login":
                    embed = discord.Embed(
                        title=" Player Connected to Divine Network",
                        description=f"**<@{uid}>** (`{uname}`) authenticated and launched Divine Client.",
                        color=TEAL,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="User", value=f"<@{uid}> (`{uname}` • ID: `{uid}`)", inline=True)
                    embed.add_field(name="Hardware Device Code", value=f"**`{dcode}`**", inline=True)
                    embed.set_footer(text=f"Log Event #{ev['id']} • Client Connected")
                    await channel.send(embed=embed)
        except Exception:
            pass

    async def _get_chat_channel(self):
        """Find or resolve the global chat log channel."""
        # 1. Configured in DB via /setchannel
        saved_id = db.get_setting("chat_channel_id")
        if saved_id and saved_id.isdigit():
            ch = self.get_channel(int(saved_id))
            if ch:
                return ch

        # 2. Configured in environment
        if CHAT_LOG_CHANNEL_ID and CHAT_LOG_CHANNEL_ID.isdigit():
            ch = self.get_channel(int(CHAT_LOG_CHANNEL_ID))
            if ch:
                return ch

        # 3. Search all guilds for divine-chat-log or chat-log
        for guild in self.guilds:
            for ch in guild.text_channels:
                if ch.name.lower() in ("divine-chat-log", "divine-chat", "client-chat-log", "divine-logs"):
                    return ch

        return None

    async def _get_audit_channel(self):
        """Find or resolve the connection & device code audit log channel."""
        # 1. Configured in DB via /setlogchannel
        saved_id = db.get_setting("audit_log_channel_id")
        if saved_id and saved_id.isdigit():
            ch = self.get_channel(int(saved_id))
            if ch:
                return ch

        # 2. Fall back to chat log channel if no dedicated audit channel set
        chat_ch = await self._get_chat_channel()
        if chat_ch:
            return chat_ch

        # 3. Search all guilds for divine-logs, device-logs, etc.
        for guild in self.guilds:
            for ch in guild.text_channels:
                if ch.name.lower() in ("divine-logs", "device-logs", "audit-logs", "mod-logs"):
                    return ch

        return None


client = DivineBot()


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"Slash command error: {error}")
    try:
        msg = f" An error occurred while running the command: {error}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


@client.event
async def on_ready():
    print(f"DivineBot online as {client.user} (shared db: {db.DB_PATH})")

    # 1. Update Discord bot username to DivineBot if allowed
    try:
        if client.user and client.user.name != "DivineBot":
            await client.user.edit(username="DivineBot")
            print("Successfully updated Discord bot username to DivineBot.")
    except Exception as e:
        print(f"Bot name update notice: {e}")

    # 2. Update Rich Presence Activity to Divine Client
    try:
        await client.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name="Divine Client 1.21.11 | /link"
            ),
            status=discord.Status.online
        )
    except Exception as e:
        print(f"Presence notice: {e}")

    # 3. Purge all cached guild-specific slash command duplicates across all servers
    for guild in client.guilds:
        try:
            client.tree.clear_commands(guild=guild)
            await client.tree.sync(guild=guild)
        except Exception:
            pass

    # 4. Synchronize unique global command tree (each command appears exactly once)
    try:
        synced = await client.tree.sync()
        print(f"Synced {len(synced)} unique global slash commands successfully.")
    except Exception as e:
        print(f"Global sync warning: {e}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip().lower()
    if content in ("!privacy", "?privacy", ".privacy", "-privacy", "/privacy"):
        try:
            embed = _build_privacy_embed()
            await message.channel.send(embed=embed)
        except Exception as e:
            print(f"Message privacy command error: {e}")
    elif content in ("!terms", "?terms", ".terms", "-terms", "/terms", "!tos", "?tos", ".tos", "/tos"):
        try:
            embed = _build_terms_embed()
            await message.channel.send(embed=embed)
        except Exception as e:
            print(f"Message terms command error: {e}")
    elif content in ("!liveplayerpanel", "!playerpanel", "!live", "!stats", "!players", "/liveplayerpanel", "/playerpanel", ".liveplayerpanel", ".playerpanel"):
        try:
            embed = _build_live_player_panel_embed()
            await message.channel.send(embed=embed)
        except Exception as e:
            print(f"Message liveplayerpanel command error: {e}")


def _build_privacy_embed():
    embed = discord.Embed(
        title=" Divine Client — Privacy Policy & Data Collection",
        description=(
            "Divine Client operates with a strict **local-first architecture** and **zero-telemetry policy**.\n"
            "Below is the complete, transparent breakdown of all data collected and processed:"
        ),
        color=TEAL,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name=" Hardware Device Code (`DEV-XXXX-...`)",
        value=(
            "A deterministic, salted cryptographic SHA-256 hash of hardware identifiers "
            "(Machine ID, Motherboard UUID, CPU architecture, MAC hash). "
            "Used strictly to enforce client hardware bans and stop malicious ban evasion."
        ),
        inline=False
    )
    embed.add_field(
        name=" Linked Discord Identity",
        value=(
            "When connecting Discord via OAuth2, we store your Discord User ID, username, and public avatar URL "
            "to authenticate launcher access and display friend status."
        ),
        inline=False
    )
    embed.add_field(
        name=" Moderation & Ban Records",
        value=(
            "When an infraction occurs, the ban reason, administering moderator ID, timestamps, "
            "and associated Hardware Device Code are stored in the server database."
        ),
        inline=False
    )
    embed.add_field(
        name=" Chat Moderation Logs",
        value=(
            "Messages sent in the Divine Global Chat Room are mirrored to a secure Discord channel "
            "to detect spam, phishing links, and hate speech."
        ),
        inline=False
    )
    embed.add_field(
        name=" 100% Local-First Storage",
        value=(
            "Minecraft instance files, worlds, saves, Fabric mods, Paper plugins, resource packs, shaders, "
            "and screenshots reside exclusively on your local drive and are never uploaded."
        ),
        inline=False
    )
    embed.add_field(
        name=" Zero Telemetry Guarantee",
        value="Zero Google Analytics, zero advertising trackers, zero spyware SDKs, and zero data selling.",
        inline=False
    )
    embed.add_field(
        name=" Official Links",
        value=f"• [Web Privacy Policy]({PUBLIC_BASE_URL}/privacy)\n• [Support & Ban Appeals]({DISCORD_INVITE_URL})",
        inline=False
    )
    embed.set_footer(text="Divine Client • Local-First & Privacy-Focused")
    return embed


def _build_terms_embed():
    embed = discord.Embed(
        title=" Divine Client — Terms of Service",
        description=(
            "By using Divine Client, our server hosting tools, Discord bot, "
            "or multiplayer tunnels, you agree to these Terms of Service:"
        ),
        color=TEAL,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name=" 1. Mojang & Microsoft EULA Compliance",
        value=(
            "Divine Client is an independent third-party platform. Users must own a legitimate Minecraft "
            "license and comply with Mojang's End User License Agreement."
        ),
        inline=False
    )
    embed.add_field(
        name=" 2. Acceptable Use & Conduct Rules",
        value=(
            "You agree not to distribute malware, host DDoS tools, transmit hateful/abusive content, "
            "or exploit multiplayer relay tunnels."
        ),
        inline=False
    )
    embed.add_field(
        name=" 3. Hardware Ban Enforcement",
        value=(
            "Violations result in permanent Hardware Device Code (`DEV-XXXX-...`) bans that block "
            "client startup, instance launching, and online connectivity across all Divine network services."
        ),
        inline=False
    )
    embed.add_field(
        name=" 4. Third-Party Mods & Paper Plugins",
        value=(
            "Mods, resource packs, shaders, and Paper plugins installed via Modrinth belong to their "
            "respective authors and licenses."
        ),
        inline=False
    )
    embed.add_field(
        name=" 5. Disclaimer of Warranty",
        value='Software is provided "as is". Divine developers are not liable for server downtime or data loss.',
        inline=False
    )
    embed.add_field(
        name=" Official Links",
        value=f"• [Web Terms of Service]({PUBLIC_BASE_URL}/terms)\n• [Discord Community]({DISCORD_INVITE_URL})",
        inline=False
    )
    embed.set_footer(text="Divine Client • Terms of Service")
    return embed


def _build_live_player_panel_embed(stats=None):
    if stats is None:
        stats = db.get_live_player_stats()

    total_registered = stats.get("total_registered", 0)
    total_online = stats.get("total_online", 0)
    playing_count = stats.get("playing_count", 0)
    in_launcher_count = stats.get("in_launcher_count", 0)
    total_offline = stats.get("total_offline", 0)
    total_devices = stats.get("total_devices", 0)
    active_servers = stats.get("active_servers", 0)
    total_bans = stats.get("total_bans", 0)

    embed = discord.Embed(
        title=" Divine Client — Live Player & Network Panel",
        description=(
            f"**Real-time status of the Divine Client network.**\n"
            f" **{total_online}** player{'s' if total_online != 1 else ''} currently active in the launcher."
        ),
        color=TEAL,
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name=" Launcher Activity",
        value=(
            f"• **Total Online:** `{total_online}`\n"
            f"• **In-Game (Playing):** `{playing_count}`\n"
            f"• **In Menus / Idle:** `{in_launcher_count}`\n"
            f"• **Offline:** `{total_offline}`"
        ),
        inline=True
    )

    embed.add_field(
        name=" Userbase & Network",
        value=(
            f"• **Linked Accounts:** `{total_registered}`\n"
            f"• **Unique Devices:** `{total_devices}`\n"
            f"• **Active Servers:** `{active_servers}`\n"
            f"• **Banned Devices:** `{total_bans}`"
        ),
        inline=True
    )

    # Active playing users list
    playing_users = stats.get("playing_users", [])
    if playing_users:
        lines = []
        for u in playing_users[:10]:
            detail = f" — *{u['detail']}*" if u.get("detail") else ""
            lines.append(f"•  **{u['username']}**{detail}")
        if len(playing_users) > 10:
            lines.append(f"*...and {len(playing_users) - 10} more players in-game*")
        embed.add_field(
            name=f" Currently In-Game ({playing_count})",
            value="\n".join(lines),
            inline=False
        )

    # In Launcher users list
    in_launcher_users = stats.get("in_launcher_users", [])
    if in_launcher_users:
        lines = []
        for u in in_launcher_users[:10]:
            lines.append(f"•  **{u['username']}** (In Launcher Menus)")
        if len(in_launcher_users) > 10:
            lines.append(f"*...and {len(in_launcher_users) - 10} more in launcher*")
        embed.add_field(
            name=f" In Launcher Menus ({in_launcher_count})",
            value="\n".join(lines),
            inline=False
        )

    if total_online == 0:
        embed.add_field(
            name=" Active Status",
            value="*No players currently active in launcher. Launch Divine Client to appear online!*",
            inline=False
        )

    embed.set_footer(text="Divine Client Live Network Monitor • Real-time Sync")
    return embed


@client.tree.command(name="liveplayerpanel", description="View live active launcher players, in-game users, and registered stats")
@app_commands.describe(ephemeral="Whether the response should only be visible to you (default: False)")
async def liveplayerpanel(interaction: discord.Interaction, ephemeral: bool = False):
    try:
        embed = _build_live_player_panel_embed()
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except Exception as e:
        print(f"/liveplayerpanel command error: {e}")
        try:
            embed = _build_live_player_panel_embed()
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Exception:
            pass


@client.tree.command(name="link", description="Connect your Discord to Divine Client")
async def link(interaction: discord.Interaction):
    _remember(interaction.user)
    embed = discord.Embed(
        title="Connect Divine Client",
        description=(
            "1. Open **Divine Client** and go to **Settings → Link Discord**.\n"
            "2. Click **Connect Discord** to get your 6-character link code.\n"
            f"3. Open {PUBLIC_BASE_URL}/link, enter the code and sign in.\n\n"
            "Once linked you can add friends, see who is online in-game, and join multiplayer servers directly!"),
        color=TEAL,
    )
    embed.set_footer(text="Divine Client")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(name="friends", description="See your Divine Client friends")
async def friends(interaction: discord.Interaction):
    _remember(interaction.user)
    uid = str(interaction.user.id)
    if not db.get_user(uid):
        await interaction.response.send_message(
            "You're not connected yet. Use `/link` to get started.", ephemeral=True)
        return
    fl = db.friends_of(uid)
    if not fl:
        await interaction.response.send_message(
            "You have no Divine friends yet. Add someone with `/addfriend`.",
            ephemeral=True)
        return
    names = "\n".join("\u2022 " + n for _id, n in fl)
    embed = discord.Embed(title="Your Divine friends", description=names, color=TEAL)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(name="addfriend", description="Send an Divine friend request")
@app_commands.describe(user="The Discord user to add as an Divine friend")
async def addfriend(interaction: discord.Interaction, user: discord.User):
    _remember(interaction.user)
    _remember(user)
    me = str(interaction.user.id)
    them = str(user.id)
    result = db.add_friendship(me, them)
    msg = {
        "self": "You can't add yourself.",
        "exists": f"You're already connected with {_display_name(user)}.",
        "accepted": f"You and {_display_name(user)} are now friends! \U0001f7e2",
        "sent": f"Friend request sent to {_display_name(user)}.",
    }.get(result, "Something went wrong.")
    await interaction.response.send_message(msg, ephemeral=True)


@client.tree.command(name="ban", description="(Admin) Ban a user or client device code from Divine Client")
@app_commands.describe(
    target="The Discord @user or Client Device Code (e.g. DEV-XXXX-XXXX-...)",
    reason="Reason for the ban (optional)"
)
async def ban(interaction: discord.Interaction, target: str, reason: str = "Violation of Terms of Service"):
    perms = getattr(interaction.user, "guild_permissions", None)
    if not perms or not (perms.manage_guild or perms.ban_members or perms.administrator):
        await interaction.response.send_message(" You do not have permission to ban clients.", ephemeral=True)
        return

    admin_name = f"{_display_name(interaction.user)} ({interaction.user.id})"
    target = target.strip()

    # Check if target is a mention e.g. <@123456>
    if target.startswith("<@") and target.endswith(">"):
        clean_id = target.strip("<@!>")
        target = clean_id

    # Check if target is a device code
    if target.upper().startswith("DEV-"):
        ok = db.ban_device(target, reason=reason, banned_by=admin_name)
        if ok:
            embed = discord.Embed(
                title=" Client Device Code Banned",
                description=f"**Device Code:** `{target.upper()}`\n**Reason:** {reason}\n**Admin:** {interaction.user.mention}",
                color=RED
            )
            embed.set_footer(text="Hardware ban enforced across all Divine network services.")
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(f" Failed to ban device code `{target}`.", ephemeral=True)
        return

    # Otherwise treat as user ID or username
    ok, msg = db.ban_user(target, reason=reason, banned_by=admin_name)
    if ok:
        embed = discord.Embed(
            title=" Divine User & Hardware Banned",
            description=f"**Target:** `{target}`\n**Reason:** {reason}\n**Details:** {msg}\n**Admin:** {interaction.user.mention}",
            color=RED
        )
        embed.set_footer(text="User and all associated hardware device codes have been suspended.")
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f" Ban failed: {msg}", ephemeral=True)


@client.tree.command(name="unban", description="(Admin) Unban a user or device code")
@app_commands.describe(target="The Discord @user, username, or Device Code (DEV-XXXX-...) to unban")
async def unban(interaction: discord.Interaction, target: str):
    perms = getattr(interaction.user, "guild_permissions", None)
    if not perms or not (perms.manage_guild or perms.ban_members or perms.administrator):
        await interaction.response.send_message(" You do not have permission to unban clients.", ephemeral=True)
        return

    clean_target = target.strip().strip("<@!>")
    ok, msg = db.unban(clean_target)
    if ok:
        embed = discord.Embed(
            title=" Ban Removed",
            description=f"**Target:** `{target}`\n**Result:** {msg}\n**Admin:** {interaction.user.mention}",
            color=TEAL
        )
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f" {msg}", ephemeral=True)


@client.tree.command(name="setchannel", description="(Admin) Set the Discord channel where Divine global chat is logged")
@app_commands.describe(channel="The channel where chat messages will be sent (leave blank for this channel)")
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    perms = getattr(interaction.user, "guild_permissions", None)
    if not perms or not (perms.manage_guild or perms.administrator or perms.manage_channels):
        await interaction.response.send_message(" You do not have permission to configure log channels.", ephemeral=True)
        return
    ch = channel or interaction.channel
    db.set_setting("chat_channel_id", str(ch.id))
    embed = discord.Embed(
        title=" Divine Chat Channel Configured",
        description=f"Divine Global Chat messages will now be relayed to {ch.mention}.",
        color=TEAL
    )
    embed.set_footer(text=f"Configured by {_display_name(interaction.user)}")
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="setlogchannel", description="(Admin) Set the channel for player connection & device code audit logs")
@app_commands.describe(channel="The channel where connection & device code logs will be sent (leave blank for this channel)")
async def setlogchannel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    perms = getattr(interaction.user, "guild_permissions", None)
    if not perms or not (perms.manage_guild or perms.administrator or perms.manage_channels):
        await interaction.response.send_message(" You do not have permission to configure log channels.", ephemeral=True)
        return
    ch = channel or interaction.channel
    db.set_setting("audit_log_channel_id", str(ch.id))
    embed = discord.Embed(
        title=" Divine Connection & Device Log Channel Configured",
        description=f"Player Discord connections and hardware device codes (`DEV-XXXX-...`) will now be logged to {ch.mention}.",
        color=TEAL
    )
    embed.set_footer(text=f"Configured by {_display_name(interaction.user)}")
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="banlist", description="(Admin) View all active banned client devices and users")
async def banlist(interaction: discord.Interaction):
    perms = getattr(interaction.user, "guild_permissions", None)
    if not perms or not (perms.manage_guild or perms.ban_members or perms.administrator):
        await interaction.response.send_message(" You do not have permission to view the ban list.", ephemeral=True)
        return

    bans = db.list_bans()
    if not bans:
        await interaction.response.send_message("ℹ No client devices or users are currently banned.", ephemeral=True)
        return

    lines = []
    for b in bans[:25]:
        dcode = b.get("device_code", "Unknown")
        uname = b.get("username") or b.get("user_id") or "Hardware Ban"
        reason = b.get("reason", "No reason provided")
        banned_at = time.strftime("%Y-%m-%d %H:%M", time.localtime(b.get("banned_at", 0)))
        lines.append(f"• **`{dcode}`** ({uname})\n  Reason: *{reason}* (at {banned_at})")

    embed = discord.Embed(
        title=f" Active Divine Bans ({len(bans)} total)",
        description="\n\n".join(lines),
        color=GOLD
    )
    embed.set_footer(text="Use /unban <target> to lift a ban.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def _handle_getcode(interaction: discord.Interaction, target: str = None, ephemeral: bool = False):
    _remember(interaction.user)

    # If no target passed, look up the caller themselves
    caller_id = str(interaction.user.id)
    is_self = False
    if not target or not target.strip():
        target = caller_id
        is_self = True
    else:
        target = target.strip()
        clean = target.lstrip("<@!").rstrip(">").strip()
        if clean == caller_id or clean.lower() == interaction.user.name.lower() or (getattr(interaction.user, 'global_name', None) and clean.lower() == interaction.user.global_name.lower()):
            is_self = True

    # Permission check if looking up someone else
    if not is_self:
        perms = getattr(interaction.user, "guild_permissions", None)
        has_perm = bool(perms and (perms.manage_guild or perms.ban_members or perms.kick_members or perms.administrator or perms.manage_messages))
        if not has_perm:
            await interaction.response.send_message(" You do not have permission to view other players' device codes.", ephemeral=True)
            return

    info = db.lookup_device_info(target)
    if not info:
        await interaction.response.send_message(
            f"ℹ No player or hardware device code found matching **`{target}`**.\n"
            f"*The user must launch Divine Client or connect their Discord in **Settings → Link Discord**.*",
            ephemeral=True
        )
        return

    # Construct rich embed response
    is_banned = info.get("banned", False)
    embed_color = RED if is_banned else TEAL

    if info["query_type"] == "device":
        dcode = info["device_code"]
        embed = discord.Embed(
            title=" Divine Hardware Device Lookup",
            description=f"Hardware Identifier: **`{dcode}`**",
            color=embed_color,
            timestamp=discord.utils.utcnow()
        )

        # Ban status
        if is_banned:
            b = info.get("ban_info") or {}
            reason = b.get("reason", "Violation of Terms of Service")
            banned_by = b.get("banned_by", "Admin")
            banned_at = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(b.get("banned_at", 0)))
            embed.add_field(
                name=" Ban Status",
                value=f"**BANNED**\n• Reason: *{reason}*\n• Moderator: {banned_by}\n• Date: {banned_at}",
                inline=False
            )
        else:
            embed.add_field(name=" Ban Status", value=" **Clean** (No active ban)", inline=False)

        # Associated users
        users = info.get("associated_users", [])
        if users:
            lines = []
            for u in users[:10]:
                uid = u["id"]
                uname = u["username"]
                ls = time.strftime("%Y-%m-%d %H:%M", time.localtime(u.get("last_seen", 0))) if u.get("last_seen") else "Never"
                lines.append(f"• <@{uid}> (`{uname}` • ID: `{uid}`) — Last seen: `{ls}`")
            embed.add_field(name=f" Linked Discord Accounts ({len(users)})", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name=" Linked Discord Accounts", value="*No Discord accounts linked to this device yet.*", inline=False)

        embed.set_footer(text=f"Queried by {_display_name(interaction.user)} | Divine Client Moderation")
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        return

    # User Query
    uid = info["user_id"]
    uname = info["username"]
    avatar = info.get("avatar_url") or ""
    presence = str(info.get("presence") or "offline")
    detail = str(info.get("presence_detail") or "")
    devices = info.get("devices", [])

    embed = discord.Embed(
        title=" Divine Client User & Device Profile",
        description=f"Discord Account: <@{uid}>\n**Username:** `{uname}`\n**User ID:** `{uid}`",
        color=embed_color,
        timestamp=discord.utils.utcnow()
    )
    if avatar:
        embed.set_thumbnail(url=avatar)

    # Presence status
    status_icon = "" if presence == "online" else ("" if presence == "in_game" else "")
    status_text = f"{status_icon} **{presence.capitalize()}**"
    if detail:
        status_text += f" ({detail})"
    embed.add_field(name="Status", value=status_text, inline=True)

    # Last seen
    ls_ts = info.get("last_seen", 0)
    ls_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ls_ts)) if ls_ts else "Never"
    embed.add_field(name="Last Seen", value=f"`{ls_str}`", inline=True)

    # Ban status
    if is_banned:
        b = info.get("ban_info") or {}
        reason = b.get("reason", "Violation of Terms of Service")
        banned_by = b.get("banned_by", "Admin")
        banned_at = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(b.get("banned_at", 0)))
        embed.add_field(
            name=" Ban Status",
            value=f"**BANNED**\n• Reason: *{reason}*\n• Moderator: {banned_by}\n• Date: {banned_at}",
            inline=False
        )
    else:
        embed.add_field(name=" Ban Status", value=" **Clean** (No active ban)", inline=False)

    # Hardware Device Codes
    if devices:
        dev_lines = []
        for d in devices:
            dcode = d["device_code"]
            d_banned = d.get("banned", False)
            d_ls = time.strftime("%Y-%m-%d %H:%M", time.localtime(d.get("last_seen", 0))) if d.get("last_seen") else "Unknown"
            status_tag = " `BANNED`" if d_banned else " `ACTIVE`"
            dev_lines.append(f"• **`{dcode}`** — {status_tag} (Active: `{d_ls}`)")
        embed.add_field(name=f" Hardware Device Code(s) ({len(devices)})", value="\n".join(dev_lines), inline=False)
    else:
        embed.add_field(
            name=" Hardware Device Code",
            value=" *No hardware device code recorded yet.*\n*(Player needs to launch the client while signed into this account)*",
            inline=False
        )

    # Quick action for admins
    if devices:
        primary_dcode = devices[0]["device_code"]
        if is_banned:
            embed.set_footer(text=f"To unban: /unban target:{primary_dcode}")
        else:
            embed.set_footer(text=f"To ban: /ban target:{primary_dcode} reason:<reason>")
    else:
        embed.set_footer(text=f"Queried by {_display_name(interaction.user)} | Divine Client Moderation")

    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)


@client.tree.command(name="lookup", description="(Admin/User) Lookup Divine user profile, hardware device code, and ban status")
@app_commands.describe(
    target="The Discord @user, username, user ID, or Device Code (leave blank for yourself)",
    ephemeral="Whether the response should only be visible to you (default: False)"
)
async def lookup(interaction: discord.Interaction, target: str = None, ephemeral: bool = False):
    await _handle_getcode(interaction, target=target, ephemeral=ephemeral)


@client.tree.command(name="generatecode", description="(Admin) Generate a redemption code for exclusive cloaks, wings, hats, cosmetics, or hosting")
@app_commands.describe(
    item_type="Reward type (cloak, wings, hat, bandana, badge, all, server_host)",
    item_id="Specific cosmetic/item ID (e.g. cloak_solaris_white, wings_angel_pure, hat_crown_gold)",
    max_uses="Maximum number of users who can claim this code (default: 1)",
    custom_code="Optional custom code text (e.g. SOLARIS-2026, leave blank to auto-generate)",
    show_in_chat="Post code publicly to Discord chat (default: True)"
)
@app_commands.choices(item_type=[
    app_commands.Choice(name="Cloak", value="cloak"),
    app_commands.Choice(name="Wings", value="wings"),
    app_commands.Choice(name="Hat / Headwear", value="hat"),
    app_commands.Choice(name="Bandana", value="bandana"),
    app_commands.Choice(name="Divine Badge", value="badge"),
    app_commands.Choice(name="Full Divine Cosmetic Bundle", value="all"),
    app_commands.Choice(name="Dedicated Server Hosting Pass", value="server_host"),
])
async def generatecode(
    interaction: discord.Interaction,
    item_type: app_commands.Choice[str] = None,
    item_id: str = "cloak_solaris_white",
    max_uses: int = 1,
    custom_code: str = None,
    show_in_chat: bool = True
):
    perms = getattr(interaction.user, "guild_permissions", None)
    if not perms or not perms.administrator:
        await interaction.response.send_message("Only server administrators can generate product redemption codes.", ephemeral=True)
        return

    type_val = item_type.value if item_type else "cloak"
    max_u = max(1, int(max_uses))

    # Format human title
    title = f"{item_id.replace('_', ' ').title()}"
    if type_val == "cloak":
        title = f"{item_id.replace('cloak_', '').replace('_', ' ').title()} Cloak"
    elif type_val == "wings":
        title = f"{item_id.replace('wings_', '').replace('_', ' ').title()} Wings"
    elif type_val == "hat":
        title = f"{item_id.replace('hat_', '').replace('_', ' ').title()} Hat"

    # Register in DB and ingame_bridge
    code_generated = None
    if ingame_bridge:
        cdata = ingame_bridge.generate_promo_code(
            item_type=type_val,
            item_id=item_id,
            title=title,
            max_uses=max_u,
            creator=f"{_display_name(interaction.user)} ({interaction.user.id})"
        )
        code_generated = cdata.get("code")

    # Also register in SQLite DB
    db_code = db.create_redeem_code(
        product_id=f"{type_val}:{item_id}",
        created_by=str(interaction.user.id),
        custom_code=code_generated or custom_code
    )
    final_code = code_generated or db_code

    embed = discord.Embed(
        title="Divine Redemption Code Generated",
        description=f"A new redemption code has been generated and added to the Divine code pool.\nThis code can be claimed **{max_u}** time{'s' if max_u > 1 else ''} directly in the Divine Client launcher or in-game!",
        color=TEAL,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Redemption Code", value=f"```\n{final_code}\n```", inline=False)
    embed.add_field(name="Reward Item", value=f"**{title}** (`{item_id}`)", inline=True)
    embed.add_field(name="Reward Type", value=f"`{type_val.upper()}`", inline=True)
    embed.add_field(name="Max Uses", value=f"`{max_u} user(s)`", inline=True)
    embed.add_field(name="Generated By", value=f"<@{interaction.user.id}>", inline=True)
    embed.add_field(
        name="How to Redeem",
        value="1. Open **Divine Client** launcher or launch in-game mod.\n2. Navigate to **Cosmetics** or press `Right Shift` -> **Redeem Code**.\n3. Paste the code above to unlock your item instantly!",
        inline=False
    )
    embed.set_footer(text="Divine Client Cosmetic & Reward Engine • Verified Code")
    await interaction.response.send_message(embed=embed, ephemeral=not show_in_chat)


@client.tree.command(name="profile", description="Check user profile, hardware device code, presence, and all redeemed codes")
@app_commands.describe(target="User mention, Discord ID, username, or hardware device code")
async def profile(interaction: discord.Interaction, target: str = None):
    query = target or str(interaction.user.id)
    info = db.resolve_target(query)
    if not info:
        await interaction.response.send_message(f" No player or device record found matching `{query}`.", ephemeral=True)
        return

    uid = info.get("user_id")
    uname = info.get("username") or "Unknown"
    codes = db.get_user_redeemed_codes(uid) if uid else []

    embed = discord.Embed(
        title=f" Player Profile: {uname}",
        color=TEAL if not info.get("banned") else RED,
        timestamp=discord.utils.utcnow()
    )
    if info.get("avatar_url"):
        embed.set_thumbnail(url=info["avatar_url"])

    embed.add_field(name="Discord Account", value=f"<@{uid}> (`{uid}`)" if uid else "*Not Linked*", inline=True)
    embed.add_field(name="Status", value=(info.get("presence") or "offline").capitalize(), inline=True)
    embed.add_field(name="Hardware Ban Status", value=" **BANNED**" if info.get("banned") else " Clean / Allowed", inline=True)

    dev_list = "\n".join([f"• `{d['device_code']}`" for d in info.get("devices", [])]) or "*No hardware registered*"
    embed.add_field(name="Registered Hardware Codes", value=dev_list, inline=False)

    if codes:
        code_lines = []
        for c in codes[:10]:
            status = " Revoked" if c.get("is_revoked") else " Active"
            ts = f"<t:{c['redeemed_at']}:R>" if c.get("redeemed_at") else "N/A"
            code_lines.append(f"• `{c['code']}` | **{c['product_id']}** ({status} • {ts})")
        embed.add_field(name=f"Redeemed Product Codes ({len(codes)})", value="\n".join(code_lines), inline=False)
    else:
        embed.add_field(name="Redeemed Product Codes", value="*No codes claimed yet*", inline=False)

    embed.set_footer(text="Divine Client Profile Check • Use /revokecode <code> to revoke any code")
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="revokecode", description="(Admin) Revoke a specific redemption code")
@app_commands.describe(code="The code to revoke (e.g. AREV-XXXX-XXXX-XXXX)")
async def revokecode(interaction: discord.Interaction, code: str):
    perms = getattr(interaction.user, "guild_permissions", None)
    if not perms or not perms.administrator:
        await interaction.response.send_message("Only administrators can revoke redemption codes.", ephemeral=True)
        return
    ok = db.revoke_code(code, revoked_by=str(interaction.user.id))
    if ok:
        embed = discord.Embed(
            title="Code Revoked Successfully",
            description=f"Redemption code **`{code.upper()}`** has been revoked and is now disabled.",
            color=RED,
            timestamp=discord.utils.utcnow()
        )
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"Code `{code}` not found or already revoked.", ephemeral=True)


@client.tree.command(name="serverlist", description="List hosted dedicated servers across the Divine network or for a specific user")
@app_commands.describe(target="Specific user mention, Discord ID, username, or device code (optional)")
async def serverlist(interaction: discord.Interaction, target: str = None):
    if target:
        info = db.resolve_target(target)
        if not info:
            await interaction.response.send_message(f"No player record found matching `{target}`.", ephemeral=True)
            return
        uid = info.get("user_id")
        uname = info.get("username") or "Unknown"
        servers = db.list_all_game_servers(host_id=uid)

        embed = discord.Embed(
            title=f"Dedicated Servers: {uname}",
            description=f"Showing hosted dedicated servers for user **{uname}** (<@{uid}>).",
            color=TEAL,
            timestamp=discord.utils.utcnow()
        )
        if not servers:
            embed.add_field(name="Servers", value="*No active or registered servers found for this user.*", inline=False)
        else:
            for s in servers[:10]:
                st = "ONLINE" if s.get("status") == "online" else "OFFLINE"
                addr = s.get("address") or "N/A"
                ver = f"{s.get('mc_version') or '1.21.1'} ({s.get('loader') or 'paper'})"
                embed.add_field(
                    name=f"{s.get('name', 'Server')} [`{s.get('code')}`]",
                    value=f"• **Status:** `{st}`\n• **Address:** `{addr}`\n• **Version:** `{ver}`",
                    inline=False
                )
        embed.set_footer(text=f"Total: {len(servers)} server(s) | Divine Server Manager")
        await interaction.response.send_message(embed=embed)
    else:
        servers = db.list_all_game_servers()
        embed = discord.Embed(
            title="Divine Network — Dedicated Servers & Live Hosts",
            description=f"Active dedicated Minecraft servers registered across the Divine network ({len(servers)} total).",
            color=TEAL,
            timestamp=discord.utils.utcnow()
        )
        if not servers:
            embed.add_field(name="Servers", value="*No dedicated servers currently registered on the network.*", inline=False)
        else:
            for s in servers[:15]:
                st = "ONLINE" if s.get("status") == "online" else "OFFLINE"
                addr = s.get("address") or "N/A"
                host_str = s.get("host_name") or f"<@{s.get('host_id')}>"
                ver = f"{s.get('mc_version') or '1.21.1'} ({s.get('loader') or 'paper'})"
                embed.add_field(
                    name=f"{s.get('name', 'Server')} [`{s.get('code')}`]",
                    value=f"• **Host:** {host_str}\n• **Status:** `{st}`\n• **Address:** `{addr}`\n• **Version:** `{ver}`",
                    inline=False
                )
        embed.set_footer(text="Divine Client Dedicated Server Hub • Use /clearserver to reset servers")
        await interaction.response.send_message(embed=embed)


@client.tree.command(name="clearserver", description="Clear and delete dedicated server records for a user or the network")
@app_commands.describe(target="User mention, Discord ID, or username whose servers should be cleared (Admin or self)")
async def clearserver(interaction: discord.Interaction, target: str = None):
    perms = getattr(interaction.user, "guild_permissions", None)
    is_admin = bool(perms and perms.administrator)

    if target:
        info = db.resolve_target(target)
        if not info:
            await interaction.response.send_message(f"No player record found matching `{target}`.", ephemeral=True)
            return
        uid = info.get("user_id")
        uname = info.get("username") or "Unknown"

        if not is_admin and str(interaction.user.id) != uid:
            await interaction.response.send_message("Only administrators can clear other players' servers.", ephemeral=True)
            return

        db.clear_user_servers(uid)
        embed = discord.Embed(
            title="User Servers Cleared",
            description=f"All hosted dedicated server records and invite codes for user **{uname}** (<@{uid}>) have been cleared.",
            color=RED,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Cleared by {_display_name(interaction.user)}")
        await interaction.response.send_message(embed=embed)
    else:
        db.clear_user_servers(str(interaction.user.id))
        embed = discord.Embed(
            title="Servers Cleared",
            description=f"All your registered dedicated server records and invite codes have been cleared from the Divine network.",
            color=RED,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Cleared by {_display_name(interaction.user)}")
        await interaction.response.send_message(embed=embed)


@client.tree.command(name="announce", description="(Server admins) post an Divine Client update")
@app_commands.describe(title="Headline", body="What's new",
                       tag="Short label, e.g. Release / Update / Fix (optional)")
async def announce(interaction: discord.Interaction, title: str, body: str,
                   tag: str = "Update"):
    perms = getattr(interaction.user, "guild_permissions", None)
    if not perms or not perms.manage_guild:
        await interaction.response.send_message(
            "Only server managers can post announcements.", ephemeral=True)
        return
    db.add_announcement(title, body, tag)
    embed = discord.Embed(title=title, description=body, color=TEAL)
    embed.set_author(name="Divine Client")
    if tag:
        embed.set_footer(text=tag)
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="privacy", description="View Divine Client Privacy Policy & all data collected")
@app_commands.describe(ephemeral="Whether the response should only be visible to you (default: False)")
async def privacy(interaction: discord.Interaction, ephemeral: bool = False):
    try:
        embed = _build_privacy_embed()
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except Exception as e:
        print(f"/privacy command error: {e}")
        try:
            embed = _build_privacy_embed()
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Exception:
            pass


@client.tree.command(name="terms", description="View Divine Client Terms of Service & acceptable use rules")
@app_commands.describe(ephemeral="Whether the response should only be visible to you (default: False)")
async def terms(interaction: discord.Interaction, ephemeral: bool = False):
    try:
        embed = _build_terms_embed()
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except Exception as e:
        print(f"/terms command error: {e}")
        try:
            embed = _build_terms_embed()
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Exception:
            pass



@client.tree.command(name="clearduplicates", description="(Admin) Force purge duplicate slash commands from this Discord server")
async def clearduplicates(interaction: discord.Interaction):
    perms = getattr(interaction.user, "guild_permissions", None)
    if not perms or not perms.administrator:
        await interaction.response.send_message("Only server administrators can purge duplicate commands.", ephemeral=True)
        return

    if interaction.guild:
        try:
            client.tree.clear_commands(guild=interaction.guild)
            await client.tree.sync(guild=interaction.guild)
        except Exception:
            pass

    await client.tree.sync()
    embed = discord.Embed(
        title=" Duplicate Slash Commands Purged",
        description="Successfully cleared server-level command overrides and synced global commands. Slash commands are now 100% deduplicated.",
        color=TEAL,
        timestamp=discord.utils.utcnow()
    )
    embed.set_author(name="DivineBot")
    embed.set_footer(text="Divine Client Moderation Engine")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@client.tree.command(name="syncfriends", description="Check Discord mutuals/friends and synchronize them with Divine Client")
async def syncfriends(interaction: discord.Interaction):
    _remember(interaction.user)
    uid = str(interaction.user.id)
    if not db.get_user(uid):
        await interaction.response.send_message(
            "You're not linked to Divine Client yet. Use `/link` to connect.", ephemeral=True)
        return

    # Check all guilds that the bot and the user share
    mutual_divine_uids = set()
    for guild in interaction.client.guilds:
        member = guild.get_member(interaction.user.id)
        if member:
            for other_member in guild.members:
                if other_member.id != interaction.user.id and not other_member.bot:
                    other_uid = str(other_member.id)
                    if db.get_user(other_uid):
                        mutual_divine_uids.add(other_uid)

    all_users = db.get_all_users_except(uid)
    for u in all_users:
        mutual_divine_uids.add(str(u["id"]))

    synced_count = db.sync_mutual_friends(uid, list(mutual_divine_uids))
    fl = db.friends_of(uid)
    names = "\n".join("• " + n for _id, n in fl) if fl else "*No other connected friends found yet.*"

    embed = discord.Embed(
        title=" Discord Friends Synchronized",
        description=f"Successfully synced **{len(fl)}** Discord friend(s) with your Divine Client launcher profile!\n\n**Friends List:**\n{names}",
        color=TEAL,
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text="Divine Client Discord Sync • Auto-Synced")
    await interaction.response.send_message(embed=embed, ephemeral=True)


def main():
    if not TOKEN:
        raise SystemExit(
            "Set DISCORD_BOT_TOKEN (Discord Developer Portal > your app > Bot > "
            "Reset Token). See server/README.md.")
    client.run(TOKEN)


if __name__ == "__main__":
    main()
