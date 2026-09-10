import discord
from discord.ext import commands
import yt_dlp
import asyncio
from datetime import datetime
import random
import os
import shutil
from flask import Flask
from threading import Thread

# ============================================
#   🌐 KEEP-ALIVE WEB SERVER (For 24/7 Render)
# ============================================
app = Flask('')

@app.route('/')
def home():
    return "JP Music Bot is Online 24/7!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ============================================
#   ⚙️ BOT CONFIGURATION
# ============================================
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

# 🚨 YAHAN APNA LOG CHANNEL ID DAALO (Discord Channel ID)
LOG_CHANNEL_ID = 123456789012345678 

# Auto-detect FFmpeg
FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"

server_states = {}

def get_state(guild_id):
    if guild_id not in server_states:
        server_states[guild_id] = {
            'queue': [],
            'loop': False,
            'volume': 1.0,
            'np_msg': None,
            'current_song': None,
            'self_disconnect': False
        }
    return server_states[guild_id]

# Stylish VC Welcome Messages
WELCOME_MESSAGES = [
    "🎧 **{name}** joined the vibe! Drop a track with `/play` 🔥",
    "🚀 Welcome **{name}** to JP GALAXY! Type `/play` 🎶",
    "✨ **{name}** is here! The session just leveled up 🎤",
    "🔥 Look who arrived — **{name}**! Start with `/play` 🎧"
]

def create_welcome_embed(member):
    message = random.choice(WELCOME_MESSAGES).format(name=member.display_name)
    embed = discord.Embed(title="🎤 Welcome to the Vibe", description=message, color=0x5865F2)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="JP MUSIC • Powered by JP GALAXY")
    return embed

# yt-dlp Configuration
YTDL_OPTIONS = {'format': 'bestaudio/best', 'noplaylist': False, 'default_search': 'ytsearch', 'quiet': True}
FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

def format_duration(seconds):
    if not seconds: return "LIVE"
    mins, secs = divmod(int(seconds), 60)
    hrs, mins = divmod(mins, 60)
    return f"{hrs}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"

def create_music_embed(state, requester):
    song = state['current_song']
    color = 0x9B59B6 if state['loop'] else 0x1ED760
    embed = discord.Embed(color=color, timestamp=datetime.utcnow())
    embed.set_author(name="🔁 LOOP ON" if state['loop'] else "▶️ NOW PLAYING", icon_url=bot.user.display_avatar.url)
    embed.title = song.get('title', 'Unknown')
    embed.url = song.get('webpage_url')
    embed.description = f"**Artist:** {song.get('uploader')} | **Time:** `{format_duration(song.get('duration'))}`\n**Vol:** `{int(state['volume']*100)}%` | **Queue:** `{len(state['queue'])}`"
    if song.get('thumbnail'): embed.set_image(url=song.get('thumbnail'))
    embed.set_footer(text=f"Requested by {requester.display_name}", icon_url=requester.display_avatar.url)
    return embed

# 🎛️ CONTROL BUTTONS
class MusicControlView(discord.ui.View):
    def __init__(self, guild_id, requester):
        super().__init__(timeout=None)
        self.guild_id, self.requester = guild_id, requester

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary)
    async def pause_btn(self, interaction, button):
        vc = interaction.guild.voice_client
        if vc.is_playing(): vc.pause(); button.emoji = "▶️"
        elif vc.is_paused(): vc.resume(); button.emoji = "⏸️"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary)
    async def skip_btn(self, interaction, button):
        if interaction.guild.voice_client: interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ Skipped!", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def loop_btn(self, interaction, button):
        state = get_state(self.guild_id)
        state['loop'] = not state['loop']
        button.style = discord.ButtonStyle.success if state['loop'] else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction, button):
        state = get_state(self.guild_id)
        state['queue'].clear(); state['self_disconnect'] = True
        if interaction.guild.voice_client: await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ Disconnected.", ephemeral=True)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=1)
    async def vol_up(self, interaction, button):
        vc = interaction.guild.voice_client
        state = get_state(self.guild_id)
        if vc and vc.source:
            state['volume'] = min(2.0, state['volume'] + 0.2)
            vc.source.volume = state['volume']
            await interaction.response.edit_message(embed=create_music_embed(state, self.requester), view=self)

# PLAYBACK ENGINE
def play_next(guild, requester, channel):
    state = get_state(guild.id)
    vc = guild.voice_client
    if not vc: return
    if state['loop'] and state['current_song']: state['queue'].insert(0, state['current_song'])
    if not state['queue']: 
        state['current_song'] = None
        return
    song = state['queue'].pop(0)
    state['current_song'] = song
    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(song['url'], executable=FFMPEG_PATH, **FFMPEG_OPTIONS), volume=state['volume'])
    vc.play(source, after=lambda e: play_next(guild, requester, channel))
    asyncio.run_coroutine_threadsafe(update_np_panel(guild, requester, channel), bot.loop)

async def update_np_panel(guild, requester, channel):
    state = get_state(guild.id)
    if state['np_msg']: 
        try: await state['np_msg'].delete()
        except: pass
    state['np_msg'] = await channel.send(embed=create_music_embed(state, requester), view=MusicControlView(guild.id, requester))

# EVENTS
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/help"))
    await bot.tree.sync()
    print(f"✅ {bot.user.name} is Online!")

@bot.event
async def on_voice_state_update(member, before, after):
    if not member.bot and before.channel is None and after.channel is not None:
        await after.channel.send(content=f"Hey {member.mention}!", embed=create_welcome_embed(member))
    
    # 🛡️ Audit Log Security
    if member.id == bot.user.id and before.channel and not after.channel:
        state = get_state(member.guild.id)
        if state['self_disconnect']: state['self_disconnect'] = False; return
        await asyncio.sleep(2)
        executor = "Unknown Admin"
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_disconnect):
            if entry.target.id == bot.user.id: executor = entry.user.mention; break
        log_ch = member.guild.get_channel(LOG_CHANNEL_ID)
        if log_ch: await log_ch.send(embed=discord.Embed(title="🚨 FORCED DISCONNECT", description=f"Bot kicked by {executor} from `{before.channel.name}`", color=0xFF0000))

# SLASH COMMANDS
@bot.tree.command(name="play", description="Play music")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    if not interaction.user.voice: return await interaction.followup.send("❌ Join VC!")
    vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect()
    state = get_state(interaction.guild.id)
    try:
        data = await asyncio.get_event_loop().run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
        if 'entries' in data:
            for e in data['entries']: state['queue'].append(e)
            await interaction.followup.send(f"📑 Playlist added!")
        else:
            state['queue'].append(data)
            await interaction.followup.send(f"✅ Added: {data['title']}")
        if not vc.is_playing(): play_next(interaction.guild, interaction.user, interaction.channel)
    except: await interaction.followup.send("❌ Error!")

@bot.tree.command(name="help", description="Commands guide")
async def help_cmd(interaction):
    emb = discord.Embed(title="🎵 JP Music Guide", description="Use `/play` to start. Buttons control everything!", color=0xFFD700)
    await interaction.response.send_message(embed=emb)

# START BOT WITH KEEP-ALIVE
keep_alive()
bot.run(os.environ.get("TOKEN"))
