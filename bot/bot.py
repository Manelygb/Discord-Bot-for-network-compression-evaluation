# bot/bot.py
import os
import pathlib
import uuid
import yaml
import aiohttp
import logging
from datetime import datetime
from dotenv import load_dotenv
import re
import asyncio

import discord
from discord.ext import commands

# ---- load .env first ----
load_dotenv()

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("model-compression-bot")

# ---------- Load config ----------
CONFIG_PATH = pathlib.Path(__file__).parent / "config.yaml"
DEFAULT_CONFIG = pathlib.Path(__file__).parent / "config.example.yaml"

if not CONFIG_PATH.exists():
    if DEFAULT_CONFIG.exists():
        with open(DEFAULT_CONFIG, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    else:
        raise FileNotFoundError("No config.yaml or config.example.yaml found in bot/")
else:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

# environment-overrides token
discord_token = os.getenv("DISCORD_TOKEN") or config["discord"].get("token")
evaluation_api_url = config["evaluation"]["api_url"]
timeout_seconds = config["evaluation"].get("timeout_seconds", 300)

SUBMISSIONS_DIR = pathlib.Path(config["submissions"].get("dir", "../submissions")).expanduser()
ALLOWED_EXTS = set(config["submissions"].get("allowed_extensions", [".pt", ".pth", ".onnx", ".tflite", ".zip"]))
MAX_FILE_SIZE_MB = config["submissions"].get("max_file_size_mb", 200)

SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Discord bot setup (message commands) ----------
intents = discord.Intents.default()
# We need message_content if we want to read text messages or use wait_for on content
intents.message_content = True

# Choose a prefix; slash-free approach avoids app_commands sync
bot = commands.Bot(command_prefix="!", intents=intents, help_command=commands.DefaultHelpCommand())

# simple URL regex for basic validation
URL_PATTERN = re.compile(r'https?://\S+')

# Helper: validate file extension from filename
def allowed_extension(filename: str) -> bool:
    return any(filename.lower().endswith(ext) for ext in ALLOWED_EXTS)

def convert_drive_link(url: str) -> str:
    """
    Convert common Google Drive view links into direct-download links.
    Returns the converted URL or the original if no change.
    """
    # direct uc links already ok
    if "drive.google.com" in url:
        # patterns:
        # https://drive.google.com/file/d/<id>/view?...  -> use id
        m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if m:
            file_id = m.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        # https://drive.google.com/open?id=<id>
        m = re.search(r'id=([a-zA-Z0-9_-]+)', url)
        if m:
            file_id = m.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        # docs.google.com/uc?id=<id>
        m = re.search(r'uc\?id=([a-zA-Z0-9_-]+)', url)
        if m:
            return url  # already fine
        # folder links or other patterns are not supported
        return url
    return url

async def download_url_to_path(url: str, dest_path: pathlib.Path, session: aiohttp.ClientSession) -> dict:
    """
    Download URL (streaming) into dest_path.
    Returns dict: {"ok": True} or {"ok": False, "error": "..."}
    Checks Content-Length vs MAX_FILE_SIZE_MB when header is present.
    """
    try:
        async with session.get(url, timeout= aiohttp.ClientTimeout(total=timeout_seconds)) as resp:
            if resp.status != 200:
                return {"ok": False, "error": f"Download failed: HTTP {resp.status}"}

            # check content-length header (if provided)
            cl = resp.headers.get("Content-Length")
            if cl:
                try:
                    cl_int = int(cl)
                    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
                    if cl_int > max_bytes:
                        return {"ok": False, "error": f"File too large ({cl_int/(1024*1024):.1f} MB). Max allowed is {MAX_FILE_SIZE_MB} MB."}
                except Exception:
                    pass

            # stream to file
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                    if not chunk:
                        break
                    f.write(chunk)

            # final sanity size check
            final_size = dest_path.stat().st_size
            if final_size == 0:
                return {"ok": False, "error": "Downloaded file is empty."}
            if final_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                return {"ok": False, "error": f"Downloaded file too large ({final_size/(1024*1024):.1f} MB). Max allowed is {MAX_FILE_SIZE_MB} MB."}

            return {"ok": True}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Download timed out."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------- Commands ----------
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (id: {bot.user.id})")
    # Show list of guilds for debugging
    logger.info("Bot is in guilds: %s", [f"{g.name} ({g.id})" for g in bot.guilds])

@bot.command(name="submit", help="Submit a model for evaluation by providing a public link (Google Drive, Dropbox, HTTP).")
async def submit(ctx, *, description: str = ""):
    """
    Usage:
      1) Run `!submit` (in DM or channel)
      2) Bot will ask for a public link (Google Drive, Dropbox, direct http(s) link)
      3) User replies with the link within the timeout (default 200s)
    """
    # prefer DM for private submissions, but allow channel
    prompt = (
        "Please provide a public link (Google Drive / Dropbox / direct http(s) link) to your model file.\n"
        f"Allowed extensions: {', '.join(sorted(ALLOWED_EXTS))}\n\n"
        "Make sure the file is accessible (anyone with the link can view/download). You have 200 seconds."
    )

    # Ask the user for a link
    try:
        await ctx.send(prompt)
    except Exception:
        # If send fails (e.g., cannot send in channel), try DM
        try:
            await ctx.author.send(prompt)
        except Exception as e:
            logger.exception("Failed to prompt user for link")
            return

    # wait for user reply with link
    def check(m: discord.Message):
        return m.author.id == ctx.author.id and m.channel == ctx.channel and bool(URL_PATTERN.search(m.content.strip()))

    # If the user is in a guild channel but prefers DM, we still accept link in same channel.
    try:
        response = await bot.wait_for("message", check=check, timeout=200)
    except asyncio.TimeoutError:
        await ctx.send("Timeout: you did not provide a valid link in time. Please run `!submit` again.")
        return

    link = response.content.strip()
    if not URL_PATTERN.match(link):
        await ctx.send("That doesn't look like a valid URL. Please run `!submit` again and provide a valid http(s) link.")
        return

    # Convert google drive view links to direct-download when possible
    link = convert_drive_link(link)

    # Build local filename and check extension from url
    url_basename = link.split("?")[0].split("/")[-1]
    # try to recover extension from name or fallback to .bin
    ext = ""
    if "." in url_basename:
        ext = "." + url_basename.split(".")[-1]
    else:
        # attempt from allowed exts
        for e in ALLOWED_EXTS:
            if e in link:
                ext = e
                break
    if ext and ext.lower() not in ALLOWED_EXTS:
        # extension present but not allowed
        await ctx.send(f"Warning: the file extension `{ext}` is not in allowed list {sorted(ALLOWED_EXTS)}. Continue anyway? (reply `yes` to confirm)")
        try:
            confirm = await bot.wait_for("message", check=lambda m: m.author.id == ctx.author.id and m.channel == ctx.channel, timeout=30)
            if confirm.content.strip().lower() != "yes":
                await ctx.send("Submission cancelled.")
                return
        except asyncio.TimeoutError:
            await ctx.send("No confirmation received — submission cancelled.")
            return

    # Prepare local path
    submission_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename_guess = url_basename or f"model{ext or '.bin'}"
    safe_name = f"{submission_id}_{timestamp}_{filename_guess}"
    dest_path = SUBMISSIONS_DIR / safe_name

    # Download using aiohttp
    await ctx.send("Downloading file (this may take a while)...")
    async with aiohttp.ClientSession() as session:
        download_res = await download_url_to_path(link, dest_path, session)
    if not download_res.get("ok"):
        await ctx.send(f"Download failed: {download_res.get('error')}")
        # cleanup
        try:
            if dest_path.exists():
                dest_path.unlink()
        except Exception:
            pass
        return

    # Verify extension after download (fallback)
    if not allowed_extension(dest_path.name):
        # if not allowed but we still downloaded, warn
        await ctx.send(f"Warning: downloaded filename `{dest_path.name}` does not match allowed extensions {sorted(ALLOWED_EXTS)}. Proceeding to submit anyway.")

    # Build metadata
    metadata = {
        "submission_id": submission_id,
        "filename": dest_path.name,
        "saved_path": str(dest_path.resolve()),
        "uploader_id": ctx.author.id,
        "uploader_name": str(ctx.author),
        "size_bytes": dest_path.stat().st_size,
        "description": description or "",
        "submitted_at": timestamp,
        "source_url": link,
    }

    # Send to evaluation API (multipart)
    try:
        logger.info(f"Posting submission {submission_id} to eval API {evaluation_api_url}")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_seconds)) as session:
            with open(dest_path, "rb") as fh:
                data = aiohttp.FormData()
                data.add_field("metadata", value=yaml.safe_dump(metadata), content_type="text/yaml")
                data.add_field("file", fh, filename=dest_path.name, content_type="application/octet-stream")

                async with session.post(evaluation_api_url, data=data) as resp:
                    text = await resp.text()
                    if resp.status in (200, 202):
                        try:
                            resp_json = await resp.json()
                        except Exception:
                            resp_json = {"job_id": None}
                        job_id = resp_json.get("job_id")
                        await ctx.send(f"Submission received ✅\nSubmission ID: `{submission_id}`\nEvaluation job ID: `{job_id}`")
                    else:
                        logger.error("Eval API error %s: %s", resp.status, text)
                        await ctx.send(f"Failed to submit to evaluation service. HTTP {resp.status}: {text}")
    except Exception as e:
        logger.exception("Error contacting evaluation API")
        await ctx.send(f"Error contacting evaluation service: {e}")

# admin ping command (non-slash)
@bot.command(name="eval_ping")
@commands.is_owner()
async def eval_ping(ctx):
    # show typing while pinging
    async with ctx.typing():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(evaluation_api_url.replace("/evaluate", "/health")) as resp:
                    text = await resp.text()
                    await ctx.send(f"Eval API: {resp.status} - {text}")
        except Exception as e:
            await ctx.send(f"Error pinging eval API: {e}")

# run the bot
if __name__ == "__main__":
    if not discord_token:
        raise RuntimeError("DISCORD_TOKEN not set (env) and not in config.yaml")
    bot.run(discord_token)
