from flask import Flask
import threading

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    app.run(host='0.0.0.0', port=8080)


import os
import discord
from discord import app_commands
from discord.ext import commands

import gspread
from google.oauth2 import service_account

# =========================
# CONFIGURATION
# =========================

# Discord bot token is taken from an environment variable named DISCORD_TOKEN
# We will set this in Render later.
TOKEN = os.environ.get("DISCORD_TOKEN")

if not TOKEN:
    print("ERROR: DISCORD_TOKEN environment variable not set.")
    raise SystemExit

# Name of the Google Sheet (the name shown at the top of the sheet)
SHEET_NAME = "VacationBot"  # change this if your sheet has a different name

# =========================
# GOOGLE SHEETS SETUP
# =========================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# This expects a file called "service_account.json" in the same folder.
# On Render, we will create this as a Secret File.
creds = service_account.Credentials.from_service_account_file(
    "service_account.json",
    scopes=SCOPES,
)

gspread_client = gspread.authorize(creds)
sheet = gspread_client.open(SHEET_NAME).sheet1  # first worksheet/tab


def find_row(username: str):
    """Find the row number where this username is stored (in column A)."""
    usernames = sheet.col_values(1)  # all values in column A
    for index, name in enumerate(usernames, start=1):
        if name.lower() == username.lower():
            return index
    return None


def set_vacation(username: str, start_date: str, end_date: str):
    """Add or update a vacation entry in the sheet."""
    row = find_row(username)
    if row is None:
        # Add new row at the bottom
        sheet.append_row([username, start_date, end_date])
    else:
        # Update existing row
        sheet.update_cell(row, 2, start_date)  # column B (Start_date)
        sheet.update_cell(row, 3, end_date)    # column C (End_date)


def remove_vacation(username: str) -> bool:
    """Remove a vacation entry. Returns True if found and deleted."""
    row = find_row(username)
    if row is None:
        return False
    sheet.delete_rows(row)
    return True


def get_vacation(username: str):
    """Get vacation entry as a dict, or None if not found."""
    row = find_row(username)
    if row is None:
        return None
    data = sheet.row_values(row)
    # data[0] = Username, data[1] = Start_date, data[2] = End_date
    if len(data) < 3:
        return None
    return {
        "username": data[0],
        "start": data[1],
        "end": data[2],
    }


# =========================
# DISCORD BOT SETUP
# =========================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print("Error syncing commands:", e)


# Create a slash command group: /vacation ...
vacation_group = app_commands.Group(
    name="vacation",
    description="Manage vacation entries",
)


@vacation_group.command(name="add", description="Add a vacation entry")
@app_commands.describe(
    username="The username or member name",
    start_date="Start date (e.g. 2025-11-21)",
    end_date="End date (e.g. 2025-11-25)",
)
async def vacation_add(
    interaction: discord.Interaction,
    username: str,
    start_date: str,
    end_date: str,
):
    set_vacation(username, start_date, end_date)
    await interaction.response.send_message(
        f"✅ Vacation added for **{username}**: `{start_date}` → `{end_date}`",
        ephemeral=True,
    )


@vacation_group.command(name="remove", description="Remove a vacation entry")
@app_commands.describe(
    username="The username or member name",
)
async def vacation_remove_cmd(
    interaction: discord.Interaction,
    username: str,
):
    success = remove_vacation(username)
    if success:
        await interaction.response.send_message(
            f"🗑️ Vacation entry removed for **{username}**.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"⚠️ No vacation entry found for **{username}**.",
            ephemeral=True,
        )


@vacation_group.command(name="view", description="View a vacation entry")
@app_commands.describe(
    username="The username or member name",
)
async def vacation_view(
    interaction: discord.Interaction,
    username: str,
):
    data = get_vacation(username)
    if data is None:
        await interaction.response.send_message(
            f"ℹ️ No vacation entry found for **{username}**.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"📅 **{data['username']}**: `{data['start']}` → `{data['end']}`",
            ephemeral=True,
        )


# Register the group with the bot
bot.tree.add_command(vacation_group)

# Start the web server on a separate thread
t = threading.Thread(target=run_web)
t.start()


# Run the bot
bot.run(TOKEN)
