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

# Keep-Alive Server
app = Flask('')
@app.route('/')
def home(): return "JP Music Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run)
    t.start()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents)

LOG_CHANNEL_ID = 1514237335464841313 
FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"
server_states = {}

def get_state(guild_id):
    if guild_id not in server_states:
        server_states[guild_id] = {'queue': [], 'loop': False, 'volume': 1.0, 'np_msg': None, 'current_song': None, 'self_disconnect': False}
    return server_states[guild_id]

# 🛡️ Updated Bypassing Options
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'default_search': 'ytsearch1',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'source_address': '0.0.0.0',
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios'],
            'player_skip': ['webpage', 'configs', 'js']
        }
    }
}

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
    embed.set_author(name="🔁 LOOP ON" if state['loop'] else "▶️ NOW PLAYING")
    embed.title = song.get('title', 'Unknown')
    embed.url = song.get('webpage_url')
    embed.description = f"**Artist:** {song.get('uploader')} | **Time:** `{format_duration(song.get('duration'))}`\n**Vol:** `{int(state['volume']*100)}%` | **Queue:** `{len(state['queue'])}`"
    if song.get('thumbnail'): embed.set_image(url=song.get('thumbnail'))
    embed.set_footer(text=f"Requested by {requester.display_name}", icon_url=requester.display_avatar.url)
    return embed

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

def play_next(guild, requester, channel):
    state = get_state(guild.id)
    vc = guild.voice_client
    if not vc: return
    
    if state['loop'] and state['current_song']:
        state['queue'].insert(0, state['current_song'])

    if not state['queue']:
        state['current_song'] = None
        return

    song = state['queue'].pop(0)
    state['current_song'] = song

    # 🛠️ Re-extracting URL right before playing to avoid expiration/blocks
    try:
        loop = asyncio.get_event_loop()
        # Direct extraction for audio URL
        info = ytdl.extract_info(song['webpage_url'], download=False)
        url = info['url']
        
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(url, executable=FFMPEG_PATH, **FFMPEG_OPTIONS), volume=state['volume'])
        vc.play(source, after=lambda e: play_next(guild, requester, channel))
        
        asyncio.run_coroutine_threadsafe(update_np_panel(guild, requester, channel), bot.loop)
    except Exception as e:
        print(f"Stream Error: {e}")
        asyncio.run_coroutine_threadsafe(channel.send(f"❌ YouTube blocked the stream for **{song['title']}**. Skipping..."), bot.loop)
        play_next(guild, requester, channel)

async def update_np_panel(guild, requester, channel):
    state = get_state(guild.id)
    if state['np_msg']: 
        try: await state['np_msg'].delete()
        except: pass
    state['np_msg'] = await channel.send(embed=create_music_embed(state, requester), view=MusicControlView(guild.id, requester))

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/help"))
    await bot.tree.sync()
    print(f"✅ {bot.user.name} Online!")

@bot.tree.command(name="play", description="Play music")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    if not interaction.user.voice: return await interaction.followup.send("❌ Join VC!")
    
    vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect()
    state = get_state(interaction.guild.id)
    
    try:
        data = await asyncio.get_event_loop().run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
        if 'entries' in data:
            if 'playlist' in data.get('webpage_url', ''):
                for e in data['entries']: state['queue'].append(e)
                await interaction.followup.send(f"📑 Playlist added!")
            else:
                song = data['entries'][0]
                state['queue'].append(song)
                await interaction.followup.send(f"✅ Added: **{song['title']}**")
        else:
            state['queue'].append(data)
            await interaction.followup.send(f"✅ Added: **{data['title']}**")
        
        if not vc.is_playing() and not vc.is_paused(): 
            play_next(interaction.guild, interaction.user, interaction.channel)
    except:
        await interaction.followup.send("❌ YouTube is blocking this search. Try a link!")

keep_alive()
bot.run(os.environ.get("TOKEN"))
