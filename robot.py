import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp
from collections import deque
import asyncio
import random
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import time
import logging

# --- Environment and Logging Setup ---
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s:%(levelname)s:%(name)s: %(message)s',
                    handlers=[
                        logging.FileHandler("bot_crash.log"),
                        logging.StreamHandler()
                    ])

# --- Global State & Theme Colors ---
SONG_QUEUES = {}
NOW_PLAYING_MESSAGES = {}
GUILD_VOLUMES = {}
THEME_COLOR_BLUE = discord.Color.from_rgb(52, 152, 219) # A nice shade of blue
THEME_COLOR_YELLOW = discord.Color.from_rgb(241, 196, 15) # A vibrant yellow

# --- Spotify and YouTube-DL Setup ---
if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET:
    spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET))
else:
    spotify = None
    print("Spotify credentials not found. Spotify integration will be disabled.")

async def search_ytdlp_async(query, ydl_opts):
    loop = asyncio.get_running_loop()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))

def get_spotify_tracks(query):
    if not spotify or "spotify.com" not in query:
        return []
    songs = []
    try:
        if "track" in query:
            track = spotify.track(query)
            songs.append(f"{track['name']} {track['artists'][0]['name']}")
        elif "playlist" in query:
            results = spotify.playlist_tracks(query)
            for item in results.get('items', []):
                track = item.get('track')
                if track:
                    songs.append(f"{track['name']} {track['artists'][0]['name']}")
        elif "album" in query:
            results = spotify.album_tracks(query)
            for track in results.get('items', []):
                if track:
                    songs.append(f"{track['name']} {track['artists'][0]['name']}")
    except Exception as e:
        print(f"Error fetching Spotify data: {e}")
        return []
    return songs

# --- UI Modals and Views ---
class VolumeModal(discord.ui.Modal, title="Set Volume"):
    volume_input = discord.ui.TextInput(label="Volume Level (1-100)", placeholder="e.g., 50 for 50% volume", min_length=1, max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.source:
            return await interaction.response.send_message("Not playing anything!", ephemeral=True)
        try:
            new_volume = int(self.volume_input.value)
            if not 1 <= new_volume <= 100:
                raise ValueError()
            voice_client.source.volume = new_volume / 100.0
            GUILD_VOLUMES[str(interaction.guild_id)] = new_volume / 100.0
            await interaction.response.send_message(f"🔊 Volume set to **{new_volume}%**.", ephemeral=True)
        except (ValueError, TypeError):
            await interaction.response.send_message("Invalid input. Please enter a number between 1 and 100.", ephemeral=True)

class MusicControls(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance

    @discord.ui.button(label="❚❚ Pause", style=discord.ButtonStyle.secondary, custom_id="pause_resume", row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client: return await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)
        if voice_client.is_playing():
            voice_client.pause()
            button.label, button.style = "▶ Resume", discord.ButtonStyle.success
        elif voice_client.is_paused():
            voice_client.resume()
            button.label, button.style = "❚❚ Pause", discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.primary, custom_id="skip", row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()
            await interaction.response.send_message("Skipped!", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing to skip.", ephemeral=True)

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger, custom_id="stop", row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        guild_id = str(interaction.guild_id)
        if guild_id in SONG_QUEUES: SONG_QUEUES[guild_id].clear()
        if voice_client and voice_client.is_connected():
            voice_client.stop()
            await voice_client.disconnect()
            await interaction.response.send_message("Stopped and left the channel.", ephemeral=True)
            if guild_id in NOW_PLAYING_MESSAGES and NOW_PLAYING_MESSAGES[guild_id]:
                try: await NOW_PLAYING_MESSAGES[guild_id].delete()
                except discord.NotFound: pass
                NOW_PLAYING_MESSAGES[guild_id] = None

    @discord.ui.button(label="🔀 Shuffle", style=discord.ButtonStyle.primary, custom_id="shuffle", row=1)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = SONG_QUEUES.get(str(interaction.guild_id))
        if queue and len(queue) > 1:
            random.shuffle(queue)
            await interaction.response.send_message("Queue shuffled!", ephemeral=True)
        else:
            await interaction.response.send_message("Not enough songs to shuffle.", ephemeral=True)

    @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.secondary, custom_id="queue", row=1)
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = SONG_QUEUES.get(str(interaction.guild_id))
        if not queue:
            return await interaction.response.send_message("The queue is empty.", ephemeral=True)
        embed = discord.Embed(title="🎶 Song Queue", color=THEME_COLOR_BLUE)
        for i, song in enumerate(list(queue)[:10]):
            embed.add_field(name=f"{i+1}. {song['title']}", value="", inline=False)
        if len(queue) > 10:
            embed.set_footer(text=f"...and {len(queue)-10} more.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔊 Volume", style=discord.ButtonStyle.secondary, custom_id="volume", row=1)
    async def volume(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VolumeModal())

# --- Bot Setup ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    bot.add_view(MusicControls(bot))
    await bot.tree.sync()
    print(f"{bot.user} is online!")

# --- Slash Commands ---
@bot.tree.command(name="join", description="Join your current voice channel")
async def join_command(interaction: discord.Interaction):
    if not interaction.user.voice or not interaction.user.voice.channel:
        return await interaction.response.send_message(embed=discord.Embed(title="❌ Error", description="You must be in a voice channel.", color=discord.Color.red()), ephemeral=True)
    try:
        await interaction.user.voice.channel.connect()
        await interaction.response.send_message(embed=discord.Embed(title="✅ Connected", description=f"Joined `{interaction.user.voice.channel.name}`.", color=THEME_COLOR_YELLOW))
    except Exception as e:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="leave", description="Leave the voice channel")
async def leave_command(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client:
        await voice_client.disconnect()
        SONG_QUEUES.pop(str(interaction.guild_id), None)
        await interaction.response.send_message(embed=discord.Embed(title="👋 Disconnected", color=THEME_COLOR_YELLOW))
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Not Connected", description="I'm not in a voice channel.", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="play", description="Play a song or add it to the queue")
@app_commands.describe(song_query="Search query or Spotify URL")
async def play_command(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()
    if not interaction.user.voice or not interaction.user.voice.channel:
        return await interaction.followup.send(embed=discord.Embed(title="❌ Error", description="You must be in a voice channel.", color=discord.Color.red()))

    voice_channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client
    if not voice_client: voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel: await voice_client.move_to(voice_channel)

    song_queries = get_spotify_tracks(song_query) or [song_query]
    guild_id = str(interaction.guild_id)
    if guild_id not in SONG_QUEUES: SONG_QUEUES[guild_id] = deque()

    added_to_queue = []
    for query in song_queries:
        try:
            ydl_opts = {"format": "bestaudio", "noplaylist": True, "quiet": True, "extract_flat": True}
            results = await search_ytdlp_async(f"ytsearch1:{query}", ydl_opts)
            if not results or not results.get('entries'): continue
            video_info = results['entries'][0]
            title = video_info.get("title", "Untitled")
            webpage_url = video_info.get("url")
            SONG_QUEUES[guild_id].append({'webpage_url': webpage_url, 'title': title})
            added_to_queue.append(title)
        except Exception as e:
            await interaction.channel.send(embed=discord.Embed(title="❌ Fetch Error", description=f"Could not fetch '{query}'.\n`{e}`", color=discord.Color.red()))

    if not added_to_queue:
        return await interaction.followup.send(embed=discord.Embed(title="❌ No Results", description="Could not find any playable songs.", color=discord.Color.red()))

    first_song_title = added_to_queue[0]
    if voice_client.is_playing() or voice_client.is_paused():
        desc = f"Added **{len(added_to_queue)}** songs." if len(added_to_queue) > 1 else f"**{first_song_title}**"
        await interaction.followup.send(embed=discord.Embed(title="✅ Added to Queue", description=desc, color=THEME_COLOR_BLUE))
    else:
        await interaction.followup.send(embed=discord.Embed(title="🎵 Let's begin!", description=f"Queued up **{first_song_title}**.", color=THEME_COLOR_YELLOW))
        await play_next_song(voice_client, guild_id, interaction.channel)

async def play_next_song(voice_client, guild_id, channel):
    if guild_id in NOW_PLAYING_MESSAGES and NOW_PLAYING_MESSAGES[guild_id]:
        try: await NOW_PLAYING_MESSAGES[guild_id].delete()
        except discord.NotFound: pass
    
    if guild_id in SONG_QUEUES and SONG_QUEUES[guild_id]:
        song_data = SONG_QUEUES[guild_id].popleft()
        title, webpage_url = song_data['title'], song_data['webpage_url']
        try:
            stream_opts = {"format": "bestaudio", "quiet": True}
            stream_results = await search_ytdlp_async(webpage_url, stream_opts)
            audio_url = stream_results['url']
            ffmpeg_options = {"before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5", "options": "-vn"}
            
            guild_volume = GUILD_VOLUMES.get(guild_id, 0.5) # Default to 50%
            source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(audio_url, **ffmpeg_options), volume=guild_volume)
            
            voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next_song(voice_client, guild_id, channel), bot.loop))
            
            embed = discord.Embed(title="🎶 Now Playing", description=f"**{title}**", color=THEME_COLOR_YELLOW)
            NOW_PLAYING_MESSAGES[guild_id] = await channel.send(embed=embed, view=MusicControls(bot))
        except Exception as e:
            await channel.send(embed=discord.Embed(title="❌ Playback Error", description=f"Could not play '{title}'. Skipping.\n`{e}`", color=discord.Color.red()))
            await play_next_song(voice_client, guild_id, channel)
    else:
        await asyncio.sleep(180)
        if voice_client.is_connected() and not voice_client.is_playing():
            await voice_client.disconnect()
            NOW_PLAYING_MESSAGES.pop(guild_id, None)

# --- Bot Runner ---
while True:
    try:
        bot.run(TOKEN, reconnect=True, log_handler=None)
    except Exception as e:
        logging.error(f"Bot crashed with error: {e}")
        print(f"Bot crashed. Restarting in 15 seconds...")
        time.sleep(15)