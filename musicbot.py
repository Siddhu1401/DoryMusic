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

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

# Setup logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s:%(levelname)s:%(name)s: %(message)s',
                    handlers=[
                        logging.FileHandler("bot_crash.log"),
                        logging.StreamHandler()
                    ])

# Per-guild song queues
SONG_QUEUES = {}

# Setup Spotify client
if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET:
    spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET))
else:
    spotify = None
    print("Spotify credentials not found. Spotify integration will be disabled.")

# --- Helper Functions ---
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

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} is online!")

# --- Music Commands ---
@bot.tree.command(name="join", description="Join your current voice channel")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Error", description="You must be in a voice channel to use this command.", color=discord.Color.red()), ephemeral=True)
        return
    try:
        await interaction.user.voice.channel.connect()
        await interaction.response.send_message(embed=discord.Embed(title="✅ Connected", description=f"Joined `{interaction.user.voice.channel.name}`.", color=discord.Color.green()))
    except Exception as e:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Connection Error", description=str(e), color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client:
        await voice_client.disconnect()
        SONG_QUEUES.pop(str(interaction.guild_id), None)
        await interaction.response.send_message(embed=discord.Embed(title="👋 Disconnected", description="Left the voice channel and cleared the queue.", color=discord.Color.blurple()))
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Not Connected", description="I'm not currently in a voice channel.", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="queue", description="Show the current song queue")
async def queue(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    queue_data = SONG_QUEUES.get(guild_id)
    if not queue_data:
        return await interaction.response.send_message(embed=discord.Embed(title="🎵 Queue is Empty", description="There are no songs in the queue.", color=discord.Color.light_grey()), ephemeral=True)

    embed = discord.Embed(title="🎶 Current Queue", color=discord.Color.blue())
    # Corrected loop to handle dictionaries
    for idx, song_info in enumerate(list(queue_data)[:10]):
        embed.add_field(name=f"{idx + 1}. {song_info['title']}", value="", inline=False)
    
    if len(queue_data) > 10:
        embed.set_footer(text=f"... and {len(queue_data) - 10} more.")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="skip", description="Skips the current song")
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        await interaction.response.send_message(embed=discord.Embed(title="⏭️ Skipped", description="Skipped the current song.", color=discord.Color.green()))
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Nothing to Skip", description="Not playing anything currently.", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="pause", description="Pause the current song")
async def pause(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await interaction.response.send_message(embed=discord.Embed(title="⏸️ Paused", description="Playback paused!", color=discord.Color.orange()))
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Nothing Playing", description="Nothing is currently playing.", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="resume", description="Resume the current song")
async def resume(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await interaction.response.send_message(embed=discord.Embed(title="▶️ Resumed", description="Playback resumed!", color=discord.Color.green()))
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Not Paused", description="Playback is not paused.", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="stop", description="Stop playback, clear queue, and disconnect")
async def stop(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    guild_id = str(interaction.guild_id)
    if guild_id in SONG_QUEUES:
        SONG_QUEUES[guild_id].clear()
    
    if voice_client and voice_client.is_connected():
        voice_client.stop()
        await voice_client.disconnect()
        await interaction.response.send_message(embed=discord.Embed(title="⏹️ Stopped", description="Playback stopped and disconnected!", color=discord.Color.dark_red()))
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Error", description="I'm not connected to a voice channel.", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="shuffle", description="Shuffle the current queue")
async def shuffle(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    queue_data = SONG_QUEUES.get(guild_id)
    if not queue_data or len(queue_data) < 2:
        return await interaction.response.send_message(embed=discord.Embed(title="❌ Not Enough Songs", description="You need at least two songs in the queue to shuffle.", color=discord.Color.red()), ephemeral=True)

    random.shuffle(queue_data)
    SONG_QUEUES[guild_id] = queue_data
    await interaction.response.send_message(embed=discord.Embed(title="🔀 Shuffled", description="The queue has been shuffled!", color=discord.Color.blue()))

@bot.tree.command(name="play", description="Play a song or add it to the queue")
@app_commands.describe(song_query="Search query or Spotify URL")
async def play(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()

    if not interaction.user.voice or not interaction.user.voice.channel:
        return await interaction.followup.send(embed=discord.Embed(title="❌ Error", description="You must be in a voice channel to play music.", color=discord.Color.red()))

    voice_channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)

    song_queries = get_spotify_tracks(song_query)
    if not song_queries:
        song_queries = [song_query]

    guild_id = str(interaction.guild_id)
    if guild_id not in SONG_QUEUES:
        SONG_QUEUES[guild_id] = deque()

    added_to_queue = []
    for query in song_queries:
        try:
            # FIX: Removed 'default_search' from here
            ydl_opts = {
                "format": "bestaudio",
                "noplaylist": True,
                "quiet": True,
                "extract_flat": True
            }
            
            # FIX: Added the search prefix directly to the query
            search_query = f"ytsearch1:{query}"
            
            results = await search_ytdlp_async(search_query, ydl_opts) # Pass the explicit search query
            
            if not results or not results.get('entries'):
                continue
            
            video_info = results['entries'][0]
            title = video_info.get("title", "Untitled")
            webpage_url = video_info.get("url")

            SONG_QUEUES[guild_id].append({'webpage_url': webpage_url, 'title': title})
            added_to_queue.append(title)
        except Exception as e:
            await interaction.channel.send(embed=discord.Embed(title="❌ Fetch Error", description=f"Could not fetch '{query}'.\n`{e}`", color=discord.Color.red()))
            continue

    if not added_to_queue:
        return await interaction.followup.send(embed=discord.Embed(title="❌ No Results", description="Could not find any playable songs for your query.", color=discord.Color.red()))

    first_song_title = added_to_queue[0]
    if voice_client.is_playing() or voice_client.is_paused():
        if len(added_to_queue) > 1:
            await interaction.followup.send(embed=discord.Embed(title="✅ Added to Queue", description=f"Added **{len(added_to_queue)}** songs.", color=discord.Color.blurple()))
        else:
            await interaction.followup.send(embed=discord.Embed(title="✅ Added to Queue", description=f"**{first_song_title}**", color=discord.Color.blurple()))
    else:
        if len(added_to_queue) > 1:
            await interaction.followup.send(embed=discord.Embed(title="🎵 Now Playing", description=f"**{first_song_title}** and added **{len(added_to_queue) - 1}** more.", color=discord.Color.green()))
        else:
            await interaction.followup.send(embed=discord.Embed(title="🎵 Now Playing", description=f"**{first_song_title}**", color=discord.Color.green()))
        
        await play_next_song(voice_client, guild_id, interaction.channel)
        
async def play_next_song(voice_client, guild_id, channel):
    if guild_id in SONG_QUEUES and SONG_QUEUES[guild_id]:
        song_data = SONG_QUEUES[guild_id].popleft()
        webpage_url = song_data['webpage_url']
        title = song_data['title']

        try:
            stream_opts = {"format": "bestaudio", "quiet": True}
            stream_results = await search_ytdlp_async(webpage_url, stream_opts)
            audio_url = stream_results['url']

            ffmpeg_options = {
                "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                "options": "-vn"
            }
            source = discord.FFmpegPCMAudio(audio_url, **ffmpeg_options)
            
            # The 'after' lambda ensures the next song plays when this one finishes or errors
            voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next_song(voice_client, guild_id, channel), bot.loop))
            
            await channel.send(embed=discord.Embed(title="🎶 Now Playing", description=f"**{title}**", color=discord.Color.green()))
        except Exception as e:
            await channel.send(embed=discord.Embed(title="❌ Playback Error", description=f"Could not play '{title}'. Skipping.\n`{e}`", color=discord.Color.red()))
            await play_next_song(voice_client, guild_id, channel)
    else:
        # Auto-disconnect after being idle
        await asyncio.sleep(180)
        if voice_client.is_connected() and not voice_client.is_playing():
            await voice_client.disconnect()
            SONG_QUEUES.pop(guild_id, None)

# --- Bot Runner with Crash Handler ---
while True:
    try:
        bot.run(TOKEN, reconnect=True, log_handler=None)
    except Exception as e:
        logging.error(f"Bot crashed with error: {e}")
        print(f"Bot crashed. Restarting in 15 seconds...")
        time.sleep(15)