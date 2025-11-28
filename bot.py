# bot.py  — Railway-ready version
import os
import json
import sys
import traceback

import discord
from discord import app_commands
from discord.ext import commands

import gspread
from google.oauth2 import service_account

print("bot.py starting...")

# ----------------------
# Config from environment
# ----------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    print("ERROR: DISCORD_TOKEN environment variable not set.")
    sys.exit(1)

# Google service account JSON stored as one env var (full JSON string)
SERVICE_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
if not SERVICE_JSON:
    print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set.")
    sys.exit(1)

# Optional: sheet name (defaults to "Vacations")
SHEET_NAME = os.environ.get("SHEET_NAME", "Vacations")

# ----------------------
# Google Sheets setup
# ----------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

try:
    print("Loading service account from env...")
    info = json.loads(SERVICE_JSON)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    print("Authorizing gspread...")
    gspread_client = gspread.authorize(creds)

    print(f"Opening sheet: '{SHEET_NAME}' ...")
    sheet = gspread_client.open(SHEET_NAME).sheet1
    print("Google Sheets connected.")
except Exception:
    print("Failed to connect to Google Sheets. Traceback:")
    traceback.print_exc()
    sys.exit(1)

# ----------------------
# Sheet helper functions
# ----------------------
def find_row(username: str):
    usernames = sheet.col_values(1)  # all values in column A
    for index, name in enumerate(usernames, start=1):
        try:
            if name and name.lower() == username.lower():
                return index
        except Exception:
            continue
    return None

def set_vacation(username: str, start_date: str, end_date: str):
    row = find_row(username)
    if row is None:
        sheet.append_row([username, start_date, end_date])
    else:
        sheet.update_cell(row, 2, start_date)
        sheet.update_cell(row, 3, end_date)

def remove_vacation(username: str) -> bool:
    row = find_row(username)
    if row is None:
        return False
    sheet.delete_rows(row)
    return True

def get_vacation(username: str):
    row = find_row(username)
    if row is None:
        return None
    data = sheet.row_values(row)
    if len(data) < 3:
        return None
    return {"username": data[0], "start": data[1], "end": data[2]}

def list_vacations():
    rows = sheet.get_all_values()
    vacations = []
    for row in rows[1:]:  # skip header
        if len(row) >= 3 and row[0]:
            vacations.append({"username": row[0], "start": row[1], "end": row[2]})
    return vacations

# ----------------------
# Discord bot
# ----------------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s) globally.")
    except Exception:
        print("Error syncing commands (traceback below):")
        traceback.print_exc()

vacation_group = app_commands.Group(name="vacation", description="Manage vacation entries")

@vacation_group.command(name="add", description="Add a vacation entry")
@app_commands.describe(username="The username or member name", start_date="Start date", end_date="End date")
async def vacation_add(interaction: discord.Interaction, username: str, start_date: str, end_date: str):
    try:
        set_vacation(username, start_date, end_date)
        await interaction.response.send_message(f"✅ Vacation added for **{username}**: `{start_date}` → `{end_date}`", ephemeral=True)
    except Exception:
        await interaction.response.send_message("❌ Failed to add vacation (see logs).", ephemeral=True)
        traceback.print_exc()

@vacation_group.command(name="remove", description="Remove a vacation entry")
@app_commands.describe(username="The username or member name")
async def vacation_remove_cmd(interaction: discord.Interaction, username: str):
    try:
        success = remove_vacation(username)
        if success:
            await interaction.response.send_message(f"🗑️ Vacation entry removed for **{username}**.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ No vacation entry found for **{username}**.", ephemeral=True)
    except Exception:
        await interaction.response.send_message("❌ Failed to remove vacation (see logs).", ephemeral=True)
        traceback.print_exc()

@vacation_group.command(name="view", description="View a vacation entry")
@app_commands.describe(username="The username or member name")
async def vacation_view(interaction: discord.Interaction, username: str):
    try:
        data = get_vacation(username)
        if data is None:
            await interaction.response.send_message(f"ℹ️ No vacation entry found for **{username}**.", ephemeral=True)
        else:
            await interaction.response.send_message(f"📅 **{data['username']}**: `{data['start']}` → `{data['end']}`", ephemeral=True)
    except Exception:
        await interaction.response.send_message("❌ Failed to read vacation (see logs).", ephemeral=True)
        traceback.print_exc()

@vacation_group.command(name="list", description="List all vacation entries")
async def vacation_list(interaction: discord.Interaction):
    try:
        vacations = list_vacations()
        if not vacations:
            await interaction.response.send_message("📭 No vacations recorded yet.", ephemeral=True)
            return
        lines = [f"• **{v['username']}**: `{v['start']}` → `{v['end']}`" for v in vacations]
        message = "\n".join(lines)
        if len(message) > 1900:
            message = "\n".join(lines[:40]) + "\n… (and more)"
        await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        await interaction.response.send_message("❌ Failed to list vacations (see logs).", ephemeral=True)
        traceback.print_exc()

bot.tree.add_command(vacation_group)

# ----------------------
# Run bot
# ----------------------
if __name__ == "__main__":
    print("Starting Discord bot...")
    bot.run(TOKEN)
