import discord
from discord import app_commands
from discord.ext import tasks
import json
import os
from datetime import datetime, timedelta, timezone

# ---------- Setup ----------

TOKEN = os.environ.get("DISCORD_TOKEN")

if not TOKEN:
    # Fallback for local testing: reads from token.txt if no env var is set
    if os.path.exists("token.txt"):
        with open("token.txt", "r") as f:
            TOKEN = f.read().strip()
    else:
        raise RuntimeError(
            "No token found. Set the DISCORD_TOKEN environment variable, "
            "or create a token.txt file with your bot token."
        )

if os.path.isdir("/data"):
    DATA_FILE = "/data/data.json"
else:
    DATA_FILE = "data.json"

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---------- Data persistence ----------

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "guild_settings": {},  # guild_id -> {"reminder_channel": id, "proof_channel": id, "reminder_time": "HH:MM"}
        "streaks": {}          # user_id -> {"count": int, "last_submitted": "YYYY-MM-DD"}
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()

# ---------- Helper functions ----------

def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def yesterday_str():
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

# ---------- Slash commands ----------

@tree.command(name="setup", description="Configure the daily drawing reminder")
@app_commands.describe(
    reminder_channel="Channel where the daily reminder will be posted",
    proof_channel="Channel where users post their drawings",
    reminder_time="Time to send the reminder, 24hr format e.g. 20:00 (UTC)"
)
async def setup(interaction: discord.Interaction, reminder_channel: discord.TextChannel,
                 proof_channel: discord.TextChannel, reminder_time: str):
    # Validate time format
    try:
        datetime.strptime(reminder_time, "%H:%M")
    except ValueError:
        await interaction.response.send_message(
            "⚠️ Please use 24hr format like `20:00`.", ephemeral=True
        )
        return

    guild_id = str(interaction.guild_id)
    data["guild_settings"][guild_id] = {
        "reminder_channel": reminder_channel.id,
        "proof_channel": proof_channel.id,
        "reminder_time": reminder_time
    }
    save_data(data)

    await interaction.response.send_message(
        f"✅ Setup complete!\n"
        f"Reminders will post in {reminder_channel.mention} at **{reminder_time} UTC**.\n"
        f"Drawings should be posted in {proof_channel.mention}."
    )

@tree.command(name="streak", description="Check your current drawing streak")
async def streak(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_data = data["streaks"].get(user_id, {"count": 0, "last_submitted": None})
    count = user_data["count"]

    if count == 0:
        msg = "You don't have a streak yet — post a drawing to start one! 🎨"
    else:
        msg = f"🔥 You're on a **{count} day streak**!"

    await interaction.response.send_message(msg, ephemeral=True)

# ---------- Image detection ----------

@client.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    guild_id = str(message.guild.id)
    settings = data["guild_settings"].get(guild_id)
    if not settings:
        return

    if message.channel.id != settings["proof_channel"]:
        return

    has_image = any(
        att.content_type and att.content_type.startswith("image/")
        for att in message.attachments
    )
    if not has_image:
        return

    user_id = str(message.author.id)
    user_data = data["streaks"].get(user_id, {"count": 0, "last_submitted": None})

    today = today_str()
    yesterday = yesterday_str()

    if user_data["last_submitted"] == today:
        # Already submitted today, don't double count
        return

    if user_data["last_submitted"] == yesterday:
        user_data["count"] += 1
    else:
        user_data["count"] = 1

    user_data["last_submitted"] = today
    data["streaks"][user_id] = user_data
    save_data(data)

    await message.channel.send(
        f"✅ Drawing submitted, {message.author.mention}!\n"
        f"🔥 {user_data['count']} day streak!"
    )

# ---------- Daily reminder loop ----------

@tasks.loop(minutes=1)
async def reminder_check():
    now = datetime.now(timezone.utc).strftime("%H:%M")
    for guild_id, settings in data["guild_settings"].items():
        if settings["reminder_time"] == now:
            channel = client.get_channel(settings["reminder_channel"])
            if channel:
                await channel.send(
                    "🎨 **DAILY DRAWING**\n"
                    f"Time to draw! Upload your drawing in <#{settings['proof_channel']}>"
                )

@reminder_check.before_loop
async def before_reminder_check():
    await client.wait_until_ready()

# ---------- Startup ----------

@client.event
async def on_ready():
    await tree.sync()
    reminder_check.start()
    print(f"🟢 Drawing Bot is online! Logged in as {client.user}")

client.run(TOKEN)
