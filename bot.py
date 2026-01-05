import os
import threading

from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands

import gspread
from google.oauth2 import service_account

# =========================
# CONFIG
# =========================

print("bot.py starting...")

# REPLACE THIS WITH YOUR SERVER ID (number only, no quotes)
GUILD_ID = 123456789012345678  # <<< put your server ID here

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    print("ERROR: DISCORD_TOKEN environment variable not set.")
    raise SystemExit(1)

# EXACT Google Sheet name (top-left in the sheet)
SHEET_NAME = "Vacations"      # <<< change if your sheet is named differently

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

print("Loading service_account.json...")
creds = service_account.Credentials.from_service_account_file(
    "service_account.json",
    scopes=SCOPES,
)

print("Authorizing gspread...")
gspread_client = gspread.authorize(creds)
sheet = gspread_client.open(SHEET_NAME).sheet1
print("Google Sheets connected.")

# =========================
# GOOGLE SHEETS HELPERS
# =========================

def find_row(username: str):
    usernames = sheet.col_values(1)  # column A
    for index, name in enumerate(usernames, start=1):
        if name.lower() == username.lower():
            return index
    return None


def set_vacation(username: str, start_date: str, end_date: str):
    row = find_row(username)
    if row is None:
        sheet.append_row([username, start_date, end_date])
    else:
        sheet.update_cell(row, 2, start_date)  # B
        sheet.update_cell(row, 3, end_date)    # C


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
    """Return all vacation records as a list of dicts."""
    rows = sheet.get_all_values()
    vacations = []
    # row 0 is header: Name | Start | End
    for row in rows[1:]:
        if len(row) >= 3 and row[0]:
            vacations.append(
                {"username": row[0], "start": row[1], "end": row[2]}
            )
    return vacations

# =========================
# DISCORD BOT
# =========================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} command(s) to guild {GUILD_ID}.")
    except Exception as e:
        print("Error syncing commands:", e)


vacation_group = app_commands.Group(
    name="vacation",
    description="Manage vacation entries",
)


@vacation_group.command(name="add", description="Add a vacation entry")
@app_commands.describe(
    username="The username or member name",
    start_date="Start date (e.g. 27th November)",
    end_date="End date (e.g. 29th November)",
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
@app_commands.describe(username="The username or member name")
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
@app_commands.describe(username="The username or member name")
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


@vacation_group.command(name="list", description="List all vacation entries")
async def vacation_list(
    interaction: discord.Interaction,
):
    vacations = list_vacations()

    if not vacations:
        await interaction.response.send_message(
            "📭 No vacations recorded yet.",
            ephemeral=True,
        )
        return

    lines = [
        f"• **{v['username']}**: `{v['start']}` → `{v['end']}`"
        for v in vacations
    ]
    message = "\n".join(lines)

    # just in case the sheet gets massive
    if len(message) > 1900:
        message = "\n".join(lines[:40]) + "\n… (and more)"

    await interaction.response.send_message(
        message,
        ephemeral=True,
    )


bot.tree.add_command(vacation_group)

# =========================
# FLASK WEB SERVER
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!"


def run_web():
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Flask web server on port {port}...")
    app.run(host="0.0.0.0", port=port)


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    print("Starting web server thread...")
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

    print("Starting Discord bot...")
    bot.run(TOKEN)
