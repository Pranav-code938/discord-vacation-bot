import os
import json
import sys
import traceback
import threading
from flask import Flask

import discord
from discord import app_commands
from discord.ext import commands

import gspread
from google.oauth2 import service_account

print("bot.py starting...")

# ----------------------
# RENDER SPECIFIC: Keep Alive / Health Check
# ----------------------
# Render Web Services require the app to bind to a specific port (default 10000)
# and return a 200 OK response to health checks.
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and healthy!", 200

def run_web_server():
    # Render sets the PORT environment variable automatically
    port = int(os.environ.get("PORT", 10000))
    # host='0.0.0.0' is required to make it accessible outside the container
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.daemon = True # Thread dies when main program dies
    t.start()

# ----------------------
# Config from environment
# ----------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    print("ERROR: DISCORD_TOKEN environment variable not set.")
    # On Render, we don't want to crash immediately if vars are missing during build,
    # but we do during runtime.
    if os.environ.get("RENDER"): 
        print("Warning: Token missing, assuming build step.")
    else:
        sys.exit(1)

# Google service account JSON stored as one env var (full JSON string)
SERVICE_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
# Optional: sheet name (defaults to "Vacations")
SHEET_NAME = os.environ.get("SHEET_NAME", "Vacations")

# ----------------------
# Google Sheets setup
# ----------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# We verify Google connection, but we wrap it to prevent crash if env var is missing
# (This happens sometimes during the initial Render Build process)
sheet = None

if SERVICE_JSON:
    try:
        print("Loading service account from env...")
        info = json.loads(SERVICE_JSON)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

        print("Authorizing gspread...")
        gspread_client = gspread.authorize(creds)

        print(f"Opening sheet: '{SHEET_NAME}' ...")
        # Note: If the sheet doesn't exist, this will throw an error.
        # Ensure the Service Account email has Editor access to the specific Sheet.
        sheet = gspread_client.open(SHEET_NAME).sheet1
        print("Google Sheets connected.")
    except Exception:
        print("Failed to connect to Google Sheets. Traceback:")
        traceback.print_exc()
        # We don't exit here, so the web server can still start (for debugging)
        # but bot commands using 'sheet' will fail.
else:
    print("WARNING: GOOGLE_SERVICE_ACCOUNT_JSON not set. Sheet commands will fail.")

# ----------------------
# Sheet helper functions
# ----------------------
def find_row(username: str):
    if not sheet: return None
    usernames = sheet.col_values(1)  # all values in column A
    for index, name in enumerate(usernames, start=1):
        try:
            if name and name.lower() == username.lower():
                return index
        except Exception:
            continue
    return None

def set_vacation(username: str, start_date: str, end_date: str):
    if not sheet: raise Exception("Database not connected")
    row = find_row(username)
    if row is None:
        sheet.append_row([username, start_date, end_date])
    else:
        sheet.update_cell(row, 2, start_date)
        sheet.update_cell(row, 3, end_date)

def remove_vacation(username: str) -> bool:
    if not sheet: raise Exception("Database not connected")
    row = find_row(username)
    if row is None:
        return False
    sheet.delete_rows(row)
    return True

def get_vacation(username: str):
    if not sheet: return None
    row = find_row(username)
    if row is None:
        return None
    data = sheet.row_values(row)
    if len(data) < 3:
        return None
    return {"username": data[0], "start": data[1], "end": data[2]}

def list_vacations():
    if not sheet: return []
    rows = sheet.get_all_values()
    vacations = []
    # Check if rows exist (handle empty sheet)
    if not rows: return []
    
    for row in rows[1:]:  # skip header
        if len(row) >= 3 and row[0]:
            vacations.append({"username": row[0], "start": row[1], "end": row[2]})
    return vacations

# ----------------------
# Discord bot
# ----------------------
intents = discord.Intents.default()
# Message Content intent is often required for prefixes, though slash commands work without it usually.
# Enabling it is safer if you switch to standard commands later.
intents.message_content = True 

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
    # Defer response if GSheets is slow
    await interaction.response.defer(ephemeral=True)
    try:
        set_vacation(username, start_date, end_date)
        await interaction.followup.send(f"✅ Vacation added for **{username}**: `{start_date}` → `{end_date}`")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to add vacation: {e}")
        traceback.print_exc()

@vacation_group.command(name="remove", description="Remove a vacation entry")
@app_commands.describe(username="The username or member name")
async def vacation_remove_cmd(interaction: discord.Interaction, username: str):
    await interaction.response.defer(ephemeral=True)
    try:
        success = remove_vacation(username)
        if success:
            await interaction.followup.send(f"🗑️ Vacation entry removed for **{username}**.")
        else:
            await interaction.followup.send(f"⚠️ No vacation entry found for **{username}**.")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to remove vacation: {e}")
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
    await interaction.response.defer(ephemeral=True)
    try:
        vacations = list_vacations()
        if not vacations:
            await interaction.followup.send("📭 No vacations recorded yet.")
            return
        lines = [f"• **{v['username']}**: `{v['start']}` → `{v['end']}`" for v in vacations]
        message = "\n".join(lines)
        if len(message) > 1900:
            message = "\n".join(lines[:40]) + "\n… (and more)"
        await interaction.followup.send(message)
    except Exception:
        await interaction.followup.send("❌ Failed to list vacations (see logs).")
        traceback.print_exc()

bot.tree.add_command(vacation_group)

# ----------------------
# Run bot
# ----------------------
if __name__ == "__main__":
    # 1. Start the Flask server in a separate thread
    print("Starting Flask Keep-Alive server...")
    keep_alive()
    
    # 2. Start the Discord bot
    if TOKEN:
        print("Starting Discord bot...")
        bot.run(TOKEN)
    else:
        print("No Token found. Web server is running, but bot is not.")
