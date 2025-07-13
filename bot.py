# Importing libraries and modules
import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp
from collections import deque
import asyncio

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Dictionary for song queues per guild
SONG_QUEUES = {}

# Function to search YouTube using yt_dlp asynchronously
async def search_ytdlp_async(query, ydl_opts):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _extract(query, ydl_opts))

def _extract(query, ydl_opts):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(query, download=False)

# Setup bot with message content intent
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# On bot ready
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} is online!")

# Join command
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

# Leave command
@bot.tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client:
        await voice_client.disconnect()
        SONG_QUEUES.pop(str(interaction.guild_id), None)
        await interaction.response.send_message(embed=discord.Embed(title="👋 Disconnected", description="Left the voice channel and cleared the queue.", color=discord.Color.blurple()))
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Not Connected", description="I'm not currently in a voice channel.", color=discord.Color.red()), ephemeral=True)

# Queue command
@bot.tree.command(name="queue", description="Show the current queue")
async def queue(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    queue = SONG_QUEUES.get(guild_id, deque())
    if not queue:
        await interaction.response.send_message(embed=discord.Embed(title="🎵 Queue is Empty", description="There are no songs in the queue.", color=discord.Color.red()), ephemeral=True)
        return

    embed = discord.Embed(title="🎶 Current Queue", color=discord.Color.blue())
    for idx, (_, title) in enumerate(queue):
        embed.add_field(name=f"{idx+1}.", value=title, inline=False)
    await interaction.response.send_message(embed=embed)

# Skip command
@bot.tree.command(name="skip", description="Skips the current playing song")
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        await interaction.response.send_message(embed=discord.Embed(title="⏭️ Skipped", description="Skipped the current song.", color=discord.Color.green()))
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Nothing to Skip", description="Not playing anything currently.", color=discord.Color.red()), ephemeral=True)

# Pause command
@bot.tree.command(name="pause", description="Pause the currently playing song.")
async def pause(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        return await interaction.response.send_message(embed=discord.Embed(title="❌ Error", description="I'm not in a voice channel.", color=discord.Color.red()), ephemeral=True)
    if not voice_client.is_playing():
        return await interaction.response.send_message(embed=discord.Embed(title="❌ Nothing Playing", description="Nothing is currently playing.", color=discord.Color.red()), ephemeral=True)
    voice_client.pause()
    await interaction.response.send_message(embed=discord.Embed(title="⏸️ Paused", description="Playback paused!", color=discord.Color.orange()))

# Resume command
@bot.tree.command(name="resume", description="Resume the currently paused song.")
async def resume(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        return await interaction.response.send_message(embed=discord.Embed(title="❌ Error", description="I'm not in a voice channel.", color=discord.Color.red()), ephemeral=True)
    if not voice_client.is_paused():
        return await interaction.response.send_message(embed=discord.Embed(title="❌ Not Paused", description="I’m not paused right now.", color=discord.Color.red()), ephemeral=True)
    voice_client.resume()
    await interaction.response.send_message(embed=discord.Embed(title="▶️ Resumed", description="Playback resumed!", color=discord.Color.green()))

# Stop command
@bot.tree.command(name="stop", description="Stop playback and clear the queue.")
async def stop(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        return await interaction.response.send_message(embed=discord.Embed(title="❌ Error", description="I'm not connected to any voice channel.", color=discord.Color.red()), ephemeral=True)
    guild_id = str(interaction.guild_id)
    SONG_QUEUES[guild_id] = deque()
    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()
    await voice_client.disconnect()
    await interaction.response.send_message(embed=discord.Embed(title="⏹️ Stopped", description="Playback stopped and disconnected!", color=discord.Color.dark_red()))

# Play command
@bot.tree.command(name="play", description="Play a song or add it to the queue.")
@app_commands.describe(song_query="Search query")
async def play(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()
    voice_state = interaction.user.voice
    if voice_state is None or voice_state.channel is None:
        return await interaction.followup.send(embed=discord.Embed(title="❌ Error", description="You must be in a voice channel to play music.", color=discord.Color.red()))
    voice_channel = voice_state.channel

    voice_client = interaction.guild.voice_client
    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_channel != voice_client.channel:
        await voice_client.move_to(voice_channel)

    ydl_opts = {
        "format": "bestaudio[abr<=96]/bestaudio",
        "noplaylist": True,
        "quiet": True,
        "extract_flat": False,
        "default_search": "ytsearch",
    }

    query = f"ytsearch1:{song_query}"
    try:
        results = await search_ytdlp_async(query, ydl_opts)
        tracks = results["entries"] if "entries" in results else [results]
    except Exception as e:
        return await interaction.followup.send(embed=discord.Embed(title="❌ Error", description=f"Failed to fetch song: {e}", color=discord.Color.red()))

    if not tracks:
        return await interaction.followup.send(embed=discord.Embed(title="❌ No Results", description="No results found.", color=discord.Color.red()))

    track = tracks[0]
    audio_url = track["url"]
    title = track.get("title", "Untitled")

    guild_id = str(interaction.guild_id)
    if guild_id not in SONG_QUEUES:
        SONG_QUEUES[guild_id] = deque()

    SONG_QUEUES[guild_id].append((audio_url, title))

    if voice_client.is_playing() or voice_client.is_paused():
        await interaction.followup.send(embed=discord.Embed(title="✅ Added to Queue", description=f"**{title}**", color=discord.Color.blurple()))
    else:
        await interaction.followup.send(embed=discord.Embed(title="🎵 Now Playing", description=f"**{title}**", color=discord.Color.green()))
        await play_next_song(voice_client, guild_id, interaction.channel)

# Play next song
async def play_next_song(voice_client, guild_id, channel):
    if SONG_QUEUES[guild_id]:
        audio_url, title = SONG_QUEUES[guild_id].popleft()
        ffmpeg_options = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn -af 'volume=1.5'"
        }
        source = discord.FFmpegPCMAudio(audio_url, **ffmpeg_options)

        def after_play(error):
            if error:
                print(f"Error: {error}")
            coro = play_next_song(voice_client, guild_id, channel)
            asyncio.run_coroutine_threadsafe(coro, bot.loop)

        voice_client.play(source, after=after_play)
        await channel.send(embed=discord.Embed(title="🎶 Now Playing", description=f"**{title}**", color=discord.Color.green()))
    else:
        await voice_client.disconnect()
        SONG_QUEUES[guild_id] = deque()

# Start the bot
bot.run(TOKEN)
