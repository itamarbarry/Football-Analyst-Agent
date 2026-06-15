import os
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directories
SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
INSTRUCTIONS_DIR = ROOT_DIR / "instructions"
RESULTS_DIR = ROOT_DIR / "results"

# Ensure directories exist
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    GEMINI_API_KEY = GEMINI_API_KEY.strip()

# Telegram Configuration (Optional)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if TELEGRAM_BOT_TOKEN:
    TELEGRAM_BOT_TOKEN = TELEGRAM_BOT_TOKEN.strip()

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
if TELEGRAM_CHAT_ID:
    TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID.strip()

def validate_config():
    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is not set. Please set it in your environment or in a .env file."
        )

def get_hebrew_translation_setting() -> bool:
    """Reads the Hebrew_Translation setting from config.json or config.JSON.
    Defaults to True if not found or if there's an error.
    """
    for filename in ["config.json", "config.JSON"]:
        config_path = ROOT_DIR / filename
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                # Look for the key case-insensitively
                for key, val in data.items():
                    if key.strip().lower() == "hebrew_translation":
                        if isinstance(val, bool):
                            return val
                        if isinstance(val, str):
                            return val.strip().upper() in ("TRUE", "1", "YES", "ON")
                        if isinstance(val, int):
                            return val != 0
            except Exception as e:
                print(f"Warning: Failed to read/parse {filename}: {e}", file=sys.stderr)
    return True

