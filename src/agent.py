import sys
import time
from datetime import datetime
import zoneinfo
import requests
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

import config

# Reconfigure stdout/stderr to UTF-8 to support emojis and Hebrew in Windows terminal
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Define structured output models for Step 1
class Match(BaseModel):
    home_team: str = Field(description="The official name of the home team")
    away_team: str = Field(description="The official name of the away team")
    match_time_israel: str = Field(description="The scheduled time of the match in Israel Time (e.g. 19:00)")
    match_time_local: str = Field(description="The scheduled time of the match in local stadium time (e.g. 13:00 Local Time)")

class MatchList(BaseModel):
    matches: list[Match] = Field(description="List of matches scheduled")

class MatchValidation(BaseModel):
    match_name: str = Field(description="The match name in format 'Home Team vs Away Team' exactly matching the list of matches.")
    is_complete: bool = Field(description="True if the analysis successfully found all critical details (current betting odds, injuries/suspensions, form). False if there are statements about missing, unavailable, or unknown info/data for this match.")
    missing_details_summary: str = Field(description="A brief explanation of what is missing or unavailable if is_complete is False, otherwise an empty string.")

class ValidationResult(BaseModel):
    results: list[MatchValidation] = Field(description="Validation results for all matches.")

def load_instruction(filename: str) -> str:
    """Loads instruction prompt from the instructions directory."""
    path = config.INSTRUCTIONS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Instruction file not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def get_current_datetime_israel() -> datetime:
    """Gets the current datetime in Asia/Jerusalem timezone."""
    israel_tz = zoneinfo.ZoneInfo("Asia/Jerusalem")
    return datetime.now(israel_tz)

STADIUM_TIMEZONES = {
    '1': 'America/Mexico_City',
    '2': 'America/Mexico_City',
    '3': 'America/Monterrey',
    '4': 'America/Chicago',
    '5': 'America/Chicago',
    '6': 'America/Chicago',
    '7': 'America/New_York',
    '8': 'America/New_York',
    '9': 'America/New_York',
    '10': 'America/New_York',
    '11': 'America/New_York',
    '12': 'America/Toronto',
    '13': 'America/Vancouver',
    '14': 'America/Los_Angeles',
    '15': 'America/Los_Angeles',
    '16': 'America/Los_Angeles',
}

STADIUM_CITIES = {
    '1': 'Mexico City',
    '2': 'Guadalajara',
    '3': 'Monterrey',
    '4': 'Dallas',
    '5': 'Houston',
    '6': 'Kansas City',
    '7': 'Atlanta',
    '8': 'Miami',
    '9': 'Boston',
    '10': 'Philadelphia',
    '11': 'New York/New Jersey',
    '12': 'Toronto',
    '13': 'Vancouver',
    '14': 'Seattle',
    '15': 'San Francisco',
    '16': 'Los Angeles',
}


def is_valid_team(team_name: str) -> bool:
    """Checks if a team name matches one of the 48 qualified World Cup 2026 teams (including common variations)."""
    import unicodedata
    if not team_name:
        return False
        
    # Standardize and normalize name
    n = team_name.strip().lower()
    
    # Remove accents/diacritics (e.g. Côte d'Ivoire -> cote d'ivoire, Curaçao -> curacao)
    n = "".join(c for c in unicodedata.normalize('NFD', n) if unicodedata.category(c) != 'Mn')
    
    # Replace symbols/common abbreviations
    n = n.replace("&", "and")
    n = n.replace("-", " ").replace(".", "").replace("'", "")
    
    # Normalize suffixes/prefixes (order matters: longer matches first)
    n = n.replace("democratic republic of the ", "").replace("democratic republic of ", "").replace("republic of the ", "").replace("republic of ", "").replace("dr ", "")
    n = n.replace("the ", "")
    n = " ".join(n.split())
    
    VALID_NORMALIZED_TEAMS = {
        "algeria", "alg", "argentina", "arg", "australia", "aus", "austria", "aut", "belgium", "bel",
        "bosnia and herzegovina", "bosnia herzegovina", "bosnia", "bih", "brazil", "brasil", "bra",
        "canada", "can", "cape verde", "cabo verde", "cpv", "colombia", "col",
        "croatia", "cro", "curacao", "cuw", "czech republic", "czechia", "cze", "congo", "congo dr", 
        "democratic republic of congo", "dr congo", "rd congo", "rdc", "cod", "ecuador", "ecu", "egypt", "egy", 
        "england", "eng", "france", "fra", "germany", "deutschland", "ger", "ghana", "gha", "haiti", "hai", 
        "iran", "islamic iran", "irn", "iraq", "irq", "ivory coast", "cote divoire", "cote d ivoire", "cote d'ivoire", "civ",
        "japan", "jpn", "jp", "jordan", "jor", "mexico", "united mexican states", "mex",
        "morocco", "mar", "netherlands", "holland", "ned", "nl", "new zealand", "nzl", "nz", "norway", "nor", 
        "panama", "pan", "paraguay", "par", "portugal", "por", "qatar", "qat", "saudi arabia", "saudi", "ksa", 
        "scotland", "sco", "senegal", "sen", "south africa", "rsa", "za",
        "south korea", "korea republic", "korea", "republic of korea", "kor", "kr", "spain", "espana", "esp", 
        "sweden", "swe", "switzerland", "sui", "ch", "tunisia", "tun", "turkey", "turkiye", "tur",
        "usa", "us", "united states", "united states of america", "america", "uruguay", "uru", "uzbekistan", "uzb"
    }
    
    return n in VALID_NORMALIZED_TEAMS

def is_placeholder_team(team_name: str) -> bool:
    """Detects if a team name is NOT a valid qualified World Cup 2026 team."""
    return not is_valid_team(team_name)

def retrieve_matches_via_api(now_israel: datetime) -> list[Match]:
    """Retrieves World Cup matches starting in the upcoming 24 hours from the current Israel time."""
    from datetime import timedelta
    
    url = "https://worldcup26.ir/get/games"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    games = data.get("games", [])
    
    matches = []
    israel_tz = zoneinfo.ZoneInfo("Asia/Jerusalem")
    
    for g in games:
        local_date_str = g.get("local_date", "")
        if not local_date_str:
            continue
        
        stadium_id = g.get("stadium_id", "11")  # Default to MetLife Stadium timezone if not found
        st_tz_name = STADIUM_TIMEZONES.get(stadium_id, 'America/New_York')
        
        try:
            # Parse the local stadium time (MM/DD/YYYY HH:MM)
            game_local_dt = datetime.strptime(local_date_str, "%m/%d/%Y %H:%M")
            # Attach stadium timezone
            game_local_dt = game_local_dt.replace(tzinfo=zoneinfo.ZoneInfo(st_tz_name))
            # Convert to Israel time
            game_israel_dt = game_local_dt.astimezone(israel_tz)
            
            # Check if game is in the upcoming 24 hours from now
            time_diff = game_israel_dt - now_israel
            if timedelta(hours=0) <= time_diff <= timedelta(hours=24):
                home = g.get("home_team_name_en")
                away = g.get("away_team_name_en")
                
                
                # Format time with date in Israel Time (keep standard YYYY-MM-DD HH:MM for LLM retrieval and analysis)
                time_part_israel = game_israel_dt.strftime("%Y-%m-%d %H:%M")
                
                # Format local time as YYYY-MM-DD HH:MM (Timezone) - City
                city_name = STADIUM_CITIES.get(stadium_id, 'New York/New Jersey')
                time_part_local = f"{game_local_dt.strftime('%Y-%m-%d %H:%M (%Z)')} - {city_name}"
                
                matches.append(Match(
                    home_team=home,
                    away_team=away,
                    match_time_israel=time_part_israel,
                    match_time_local=time_part_local
                ))
        except ValueError as e:
            # Re-raise value errors (like placeholders) to trigger fallback cascade
            raise e
        except Exception:
            continue
    return matches

def retrieve_matches_via_secondary_api(now_israel: datetime) -> list[Match]:
    """Retrieves World Cup matches starting in the upcoming 24 hours from the secondary JSON API (thestatsapi.com)."""
    from datetime import timedelta
    url = "https://www.thestatsapi.com/world-cup/data/fixtures.json"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    fixtures = data.get("fixtures", [])
    
    matches = []
    israel_tz = zoneinfo.ZoneInfo("Asia/Jerusalem")
    
    CITY_TIMEZONES = {
        'mexico-city': 'America/Mexico_City',
        'guadalajara': 'America/Mexico_City',
        'monterrey': 'America/Monterrey',
        'dallas': 'America/Chicago',
        'houston': 'America/Chicago',
        'kansas-city': 'America/Chicago',
        'atlanta': 'America/New_York',
        'miami': 'America/New_York',
        'boston': 'America/New_York',
        'philadelphia': 'America/New_York',
        'new-york': 'America/New_York',
        'toronto': 'America/Toronto',
        'vancouver': 'America/Vancouver',
        'los-angeles': 'America/Los_Angeles',
        'seattle': 'America/Los_Angeles',
        'san-francisco': 'America/Los_Angeles',
    }
    
    for f in fixtures:
        home = f.get("homeTeam")
        away = f.get("awayTeam")
        kickoff_utc_str = f.get("kickoffUtc")
        if not home or not away or not kickoff_utc_str:
            continue
            
        try:
            # Parse ISO UTC date string
            game_utc_dt = datetime.fromisoformat(kickoff_utc_str.replace('Z', '+00:00'))
            game_israel_dt = game_utc_dt.astimezone(israel_tz)
            
            # Check if game is in the upcoming 24 hours from now
            time_diff = game_israel_dt - now_israel
            if timedelta(hours=0) <= time_diff <= timedelta(hours=24):

                time_part_israel = game_israel_dt.strftime("%Y-%m-%d %H:%M")
                
                host_city_key = f.get("hostCity", "").lower().replace(' ', '-').strip()
                tz_name = CITY_TIMEZONES.get(host_city_key, 'America/New_York')
                game_local_dt = game_utc_dt.astimezone(zoneinfo.ZoneInfo(tz_name))
                
                city_name = f.get("hostCity", "New York/New Jersey")
                time_part_local = f"{game_local_dt.strftime('%Y-%m-%d %H:%M (%Z)')} - {city_name}"
                
                matches.append(Match(
                    home_team=home,
                    away_team=away,
                    match_time_israel=time_part_israel,
                    match_time_local=time_part_local
                ))
        except ValueError as e:
            raise e
        except Exception:
            continue
            
    return matches

def retrieve_matches_via_tertiary_api(now_israel: datetime) -> list[Match]:
    """Retrieves World Cup matches starting in the upcoming 24 hours from the tertiary OpenFootball JSON API."""
    import re
    from datetime import timezone, timedelta
    
    url = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    matches_raw = data.get("matches", [])
    
    matches = []
    israel_tz = zoneinfo.ZoneInfo("Asia/Jerusalem")
    
    GROUND_TIMEZONES = {
        'mexico city': 'America/Mexico_City',
        'guadalajara (zapopan)': 'America/Mexico_City',
        'monterrey (guadalupe)': 'America/Monterrey',
        'dallas (arlington)': 'America/Chicago',
        'houston': 'America/Chicago',
        'kansas city': 'America/Chicago',
        'atlanta': 'America/New_York',
        'miami (miami gardens)': 'America/New_York',
        'boston (foxborough)': 'America/New_York',
        'philadelphia': 'America/New_York',
        'new york/new jersey (east rutherford)': 'America/New_York',
        'toronto': 'America/Toronto',
        'vancouver': 'America/Vancouver',
        'los angeles (inglewood)': 'America/Los_Angeles',
        'seattle': 'America/Los_Angeles',
        'san-francisco': 'America/Los_Angeles',
        'san francisco bay area (santa clara)': 'America/Los_Angeles',
    }
    
    for m in matches_raw:
        home = m.get("team1")
        away = m.get("team2")
        date_str = m.get("date")
        time_str = m.get("time")
        ground = m.get("ground", "")
        
        if not home or not away or not date_str or not time_str:
            continue
            
        try:
            # Parse time_str (e.g. "13:00 UTC-6")
            match = re.match(r"(\d{1,2}):(\d{2})\s+UTC([+-]\d+)", time_str)
            if not match:
                continue
                
            hour = int(match.group(1))
            minute = int(match.group(2))
            offset_hours = int(match.group(3))
            
            base_dt = datetime.strptime(date_str, "%Y-%m-%d")
            tz = timezone(timedelta(hours=offset_hours))
            game_utc_dt = datetime(base_dt.year, base_dt.month, base_dt.day, hour, minute, tzinfo=tz).astimezone(timezone.utc)
            game_israel_dt = game_utc_dt.astimezone(israel_tz)
            
            # Check if game is in the upcoming 24 hours from now
            time_diff = game_israel_dt - now_israel
            if timedelta(hours=0) <= time_diff <= timedelta(hours=24):
                if is_placeholder_team(home) or is_placeholder_team(away):
                    raise ValueError(f"Placeholder team detected in tertiary API: {home} vs {away}")
                    
                time_part_israel = game_israel_dt.strftime("%Y-%m-%d %H:%M")
                
                ground_key = ground.lower().strip()
                tz_name = GROUND_TIMEZONES.get(ground_key, 'America/New_York')
                game_local_dt = game_utc_dt.astimezone(zoneinfo.ZoneInfo(tz_name))
                
                time_part_local = f"{game_local_dt.strftime('%Y-%m-%d %H:%M (%Z)')} - {ground}"
                
                matches.append(Match(
                    home_team=home,
                    away_team=away,
                    match_time_israel=time_part_israel,
                    match_time_local=time_part_local
                ))
        except ValueError as e:
            raise e
        except Exception:
            continue
            
    return matches

def generate_content_with_retry(client, model, contents, config=None, max_retries=15):
    """Generates content with retry logic, falling back to other models if the primary model fails."""
    # List of fallback models to rotate through in case of temporary model-specific availability issues
    fallbacks = ["gemini-2.5-flash", "gemini-3.5-flash"]
    
    # Ensure the requested model is at the front of the list, without duplicates
    models_to_try = [model]
    for fb in fallbacks:
        if fb not in models_to_try:
            models_to_try.append(fb)
            
    current_model_idx = 0
    
    for attempt in range(1, max_retries + 1):
        active_model = models_to_try[current_model_idx]
        try:
            return client.models.generate_content(
                model=active_model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            err_msg = str(e).lower()
            status_code = getattr(e, 'code', None)
            
            # Check for permanent authentication or client configuration errors
            is_permanent = False
            if status_code in (401, 403):
                is_permanent = True
            elif "api_key" in err_msg or "api key" in err_msg or "invalid api key" in err_msg or "key not valid" in err_msg:
                is_permanent = True
            elif "permission_denied" in err_msg or "unauthorized" in err_msg:
                is_permanent = True
            
            if is_permanent or attempt == max_retries:
                raise e
            
            # Rotate to the next model in the chain on failure
            next_idx = (current_model_idx + 1) % len(models_to_try)
            next_model = models_to_try[next_idx]
            
            wait_time = min(attempt * 3, 15)
            print(f"   ⚠️ Gemini API call failed on model '{active_model}': {e}.", flush=True)
            print(f"       Retrying with model '{next_model}' in {wait_time}s (Attempt {attempt}/{max_retries})...", flush=True)
            
            current_model_idx = next_idx
            time.sleep(wait_time)

def markdown_to_telegram_html(text: str) -> str:
    """Converts basic markdown elements to Telegram-friendly HTML tags."""
    import re
    # Escape HTML special characters first
    html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # Convert headers (# Title, ## Subtitle) to bold
    html = re.sub(r'^#+\s+(.*)$', r'<b>\1</b>', html, flags=re.MULTILINE)
    
    # Convert bold (**text**) to <b>text</b>
    html = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html)
    
    # Convert bullet points (* text or - text) to • text
    html = re.sub(r'^\s*[\*\-]\s+', r'• ', html, flags=re.MULTILINE)
    
    # Remove horizontal rule lines
    html = re.sub(r'^---$', r'', html, flags=re.MULTILINE)
    
    # Strip excess blank lines (max 2 consecutive newlines)
    html = re.sub(r'\n{3,}', r'\n\n', html)
    
    # If the text has Hebrew characters, prepend RLM (\u200f) to each non-empty line
    # to force correct RTL alignment in Telegram for all elements (headers, text)
    if re.search(r'[\u0590-\u05fe]', html):
        lines = html.split('\n')
        html = '\n'.join(('\u200f' + line if line.strip() else line) for line in lines)
        
    return html.strip()

def post_to_telegram(message_text: str):
    """Sends the daily summary message to the configured Telegram channel/group, splitting if necessary."""
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        print("   ⚠️ Telegram Bot Token or Chat ID not set. Skipping Telegram post.")
        return
        
    print("   📤 Broadcasting summary to Telegram channel...")
    formatted_html = markdown_to_telegram_html(message_text)
    
    max_len = 4095
    if len(formatted_html) <= max_len:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": formatted_html,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            print("   ✅ Telegram broadcast posted successfully!")
        except Exception as e:
            print(f"   ❌ Failed to send Telegram message: {e}", file=sys.stderr)
            try:
                print(f"      Response body: {response.text}", file=sys.stderr)
            except Exception:
                pass
            raise e
        return

    # Split into chunks of max 4095 characters
    lines = formatted_html.split('\n')
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        if current_len + len(line) + 1 > max_len:
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_len = len(line)
        else:
            current_chunk.append(line)
            current_len += len(line) + 1

    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    for i, chunk in enumerate(chunks, 1):
        print(f"      [Chunk {i}/{len(chunks)}] Sending ({len(chunk)} chars)...")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": chunk.strip(),
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            print(f"      ✅ Chunk {i} posted successfully!")
        except Exception as e:
            print(f"      ❌ Failed to send Chunk {i}: {e}", file=sys.stderr)
            try:
                print(f"         Response body: {response.text}", file=sys.stderr)
            except Exception:
                pass
            raise e
        time.sleep(1)

def is_matchday(dt: datetime) -> bool:
    """Checks if the given datetime is an active World Cup 2026 matchday."""
    if dt.year != 2026:
        return False
    
    # June 11 to June 30
    if dt.month == 6:
        return 11 <= dt.day <= 30
        
    # July 1 to July 19, excluding rest days: July 8, 11, 13, 16, 17, 18
    if dt.month == 7:
        if 1 <= dt.day <= 19:
            rest_days = {8, 11, 13, 16, 17, 18}
            return dt.day not in rest_days
            
    return False

def run_pipeline():
    # 0. Validate config
    try:
        config.validate_config()
    except ValueError as e:
        print(f"❌ Configuration Error: {e}", file=sys.stderr)
        sys.exit(1)

    hebrew_translation = config.get_hebrew_translation_setting()

    # Initialize Gemini Client with a 45-second HTTP timeout to prevent long search grounding hangs
    client = genai.Client(api_key=config.GEMINI_API_KEY, http_options={"timeout": 45000.0})
    model_name = "gemini-2.5-pro"

    # Get current date and datetime in Israel Time
    now_israel = get_current_datetime_israel()
    force_run = "--force" in sys.argv
    if not is_matchday(now_israel) and not force_run:
        print("=" * 60)
        print(f"📅 Today ({now_israel.strftime('%Y-%m-%d')}) is a rest day or outside the tournament window.")
        print("⚽ Skipping pipeline execution. Use --force to override.")
        print("=" * 60)
        sys.exit(0)
    if hebrew_translation:
        today_str = now_israel.strftime("%d/%m/%y")
    else:
        today_str = now_israel.strftime("%Y-%m-%d")
        
    now_israel_str = now_israel.strftime("%Y-%m-%d %H:%M")
    file_timestamp_str = now_israel.strftime("%d-%m-%y_%H-%M")
    
    from datetime import timedelta
    end_window_israel = (now_israel + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    
    print("=" * 60)
    print("⚽ FOOTBALL ANALYST AGENT STARTING")
    print(f"📅 Current Israel Time: {now_israel_str}")
    print(f"⏳ Analysis Time Window: {now_israel_str} to {end_window_israel} (Israel Time)")
    print("=" * 60)

    # ==========================================
    # Step 1: Retrieve upcoming World Cup games
    # ==========================================
    print("\n[Step 1] Retrieving scheduled matches for the next 24 hours...")
    matches = []
    
    # 1. Try Primary API
    try:
        print("   🔄 Connecting to World Cup 2026 REST API (Primary)...")
        matches = retrieve_matches_via_api(now_israel)
        if matches:
            print(f"   ✅ Primary API Successful! Retrieved {len(matches)} matches.")
        else:
            print("   ⚠️ Primary API returned 0 matches. Trying fallback APIs...")
    except Exception as e:
        print(f"   ⚠️ Primary API Failed: {e}")
        
    # 2. Try Secondary API if no matches found
    if not matches:
        try:
            print("   🔄 Connecting to World Cup Fixtures JSON API (Secondary)...")
            matches = retrieve_matches_via_secondary_api(now_israel)
            if matches:
                print(f"   ✅ Secondary API Successful! Retrieved {len(matches)} matches.")
            else:
                print("   ⚠️ Secondary API returned 0 matches. Trying fallback APIs...")
        except Exception as e:
            print(f"   ⚠️ Secondary API Failed: {e}")
            
    # 3. Try Tertiary API if no matches found
    if not matches:
        try:
            print("   🔄 Connecting to OpenFootball JSON API (Tertiary)...")
            matches = retrieve_matches_via_tertiary_api(now_israel)
            if matches:
                print(f"   ✅ Tertiary API Successful! Retrieved {len(matches)} matches.")
            else:
                print("   ⚠️ Tertiary API returned 0 matches. Falling back to search grounding...")
        except Exception as e:
            print(f"   ⚠️ Tertiary API Failed: {e}")
            
    # 4. Try Search Grounding if all APIs returned 0 matches or failed
    if not matches:
        print("   🔄 Falling back to Gemini search grounding for match retrieval...")
        import json
        
        retrieve_instr = load_instruction("retrieve_games.md").format(current_datetime=now_israel_str)
        retrieve_instr += "\n\nCRITICAL: You must return the output as a raw JSON object matching the MatchList schema (a dictionary with a 'matches' key containing a list of match objects). Do not wrap the JSON in markdown code blocks, and do not write any explanation outside the JSON."
        
        # Enable search grounding for match retrieval fallback
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config_retrieval = types.GenerateContentConfig(
            tools=[grounding_tool],
        )

        try:
            response = generate_content_with_retry(
                client=client,
                model=model_name,
                contents=retrieve_instr,
                config=config_retrieval,
            )
            resp_text = response.text.strip()
            
            # Clean up potential markdown code block wrappers
            if resp_text.startswith("```"):
                lines = resp_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                resp_text = "\n".join(lines).strip()
            
            data = json.loads(resp_text)
            matches_data = data.get("matches", [])
            for m in matches_data:
                matches.append(Match(
                    home_team=m.get("home_team"),
                    away_team=m.get("away_team"),
                    match_time_israel=m.get("match_time_israel"),
                    match_time_local=m.get("match_time_local")
                ))
            print(f"   ✅ Fallback Gemini Search Retrieval Successful! Retrieved {len(matches)} matches.")
        except Exception as fallback_err:
            print(f"   ❌ Critical Error in fallback retrieval: {fallback_err}", file=sys.stderr)
            sys.exit(1)

    if not matches:
        print("   📊 No matches scheduled for the next 24 hours.")
        hebrew_translation = config.get_hebrew_translation_setting()
        if hebrew_translation:
            print("   📝 Writing a rest-day notice in Hebrew...")
            rest_day_msg = f"# מונדיאל 2026 - סיכום יומי\n\nתאריך: {today_str}\n\nאין משחקים מתוכננים ב-24 השעות הקרובות בטורניר גביע העולם. זהו יום מנוחה לקבוצות ולשחקנים. נתראה במחזורים הבאים!"
        else:
            print("   📝 Writing a rest-day notice in English...")
            rest_day_msg = f"# World Cup 2026 - Daily Summary\n\nDate: {today_str}\n\nThere are no matches scheduled for the next 24 hours in the World Cup. This is a rest day for the teams and players. See you in the next rounds!"
        
        output_file = config.RESULTS_DIR / f"{file_timestamp_str}.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(rest_day_msg)
        print(f"   💾 Saved rest-day summary to {output_file}")
        post_to_telegram(rest_day_msg)
        print("=" * 60)
        return

    # Sort matches chronologically by Israel Time
    def get_match_sort_key(m: Match):
        for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M", "%d-%m-%Y %H:%M"):
            try:
                return datetime.strptime(m.match_time_israel.strip(), fmt)
            except ValueError:
                continue
        return m.match_time_israel

    matches.sort(key=get_match_sort_key)

    print(f"   📊 Found {len(matches)} match(es) in the upcoming 24 hours (ordered chronologically):")
    for m in matches:
        print(f"      • {m.home_team} vs {m.away_team}:")
        print(f"        - Israel Time: {m.match_time_israel}")
        print(f"        - Local Time:  {m.match_time_local}")

    # ==========================================
    # Step 2 & 3: Analyze and Predict each game individually
    # ==========================================
    print("\n" + "-" * 60)
    print("[Step 2 & 3] Researching and Predicting Matches (Individual Calls)")
    print("-" * 60)
    
    # Map each match to its latest analysis text, retry/attempt state, and feedback
    # Keys will be "Home Team vs Away Team"
    match_analyses = {}
    match_attempts = {f"{m.home_team} vs {m.away_team}": 0 for m in matches}
    match_missing_feedback = {f"{m.home_team} vs {m.away_team}": "" for m in matches}
    
    max_pipeline_attempts = 3
    pipeline_attempt = 1
    
    analyze_instr_template = load_instruction("analyze_game.md")
    predict_instr_template = load_instruction("predict_game.md")
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    
    while pipeline_attempt <= max_pipeline_attempts:
        print(f"\n🔄 Pipeline Validation Attempt {pipeline_attempt}/{max_pipeline_attempts}...")
        
        # Determine which matches need to be analyzed (or re-analyzed)
        matches_to_analyze = []
        for m in matches:
            m_key = f"{m.home_team} vs {m.away_team}"
            if m_key not in match_analyses:
                matches_to_analyze.append(m)
                
        if not matches_to_analyze:
            print("   ✅ No matches need analysis/re-analysis in this iteration.")
        else:
            print(f"   🔍 Analyzing {len(matches_to_analyze)} match(es)...")
            for m in matches_to_analyze:
                m_key = f"{m.home_team} vs {m.away_team}"
                match_attempts[m_key] += 1
                curr_attempt = match_attempts[m_key]
                
                print(f"      👉 Researching and predicting {m_key} (Match Attempt {curr_attempt})...")
                
                extra_instruction = ""
                if curr_attempt > 1:
                    feedback = match_missing_feedback.get(m_key, "")
                    feedback_str = f" (specifically: {feedback})" if feedback else ""
                    extra_instruction = (
                        f"\n\n⚠️ RETRY WARNING (Attempt {curr_attempt}): In the previous attempt, "
                        f"the validator flagged that some information{feedback_str} was missing, unavailable, or could not be found. "
                        f"This information IS available on the web. Please perform a more thorough search using different/broader queries (e.g. searching ESPN, WhoScored, Bet365, "
                        f"Oddsportal, rotowire, wiki, etc. for '{m.home_team} vs {m.away_team}'), and ensure that every section is populated with concrete facts, "
                        f"odds, and injury details instead of writing 'not available'."
                    )
                
                match_prompt = (
                    f"You are a professional football analyst and tipster. Your task is to perform web research "
                    f"and make scoreline/winner predictions for the upcoming match:\n\n"
                    f"Match: {m.home_team} vs {m.away_team}\n"
                    f"Scheduled Time (Israel Time): {m.match_time_israel}\n"
                    f"Scheduled Time (Local Time): {m.match_time_local}\n\n"
                    f"--- RESEARCH GUIDELINES ---\n"
                    f"{analyze_instr_template.format(home_team=m.home_team, away_team=m.away_team, date=today_str)}\n\n"
                    f"--- PREDICTION GUIDELINES ---\n"
                    f"{predict_instr_template.format(home_team=m.home_team, away_team=m.away_team, analysis_context='(Use your research findings to predict)')}"
                    f"{extra_instruction}"
                )
                
                try:
                    config_analysis = types.GenerateContentConfig(tools=[grounding_tool])
                    analysis_resp = generate_content_with_retry(
                        client=client,
                        model=model_name,
                        contents=match_prompt,
                        config=config_analysis,
                    )
                    match_analyses[m_key] = analysis_resp.text
                except Exception as e:
                    print(f"      ❌ Error researching {m_key}: {e}", file=sys.stderr)
                    if pipeline_attempt == max_pipeline_attempts:
                        raise e
                    continue
        
        # Build the combined report to send to the Validator LLM
        combined_report_list = []
        for idx, m in enumerate(matches, start=1):
            m_key = f"{m.home_team} vs {m.away_team}"
            analysis_text = match_analyses.get(m_key, "[No analysis generated yet]")
            combined_report_list.append(
                f"=========================================\n"
                f"MATCH {idx}: {m_key}\n"
                f"=========================================\n"
                f"{analysis_text}\n"
            )
        combined_report_str = "\n".join(combined_report_list)
        
        # Run Validator LLM
        print("   🔍 Validating combined match analyses and predictions...")
        validator_prompt = (
            f"You are a strict validation agent. Your job is to check the combined match report below "
            f"and determine if all critical details (current betting odds, injuries/suspensions, and form) "
            f"were successfully retrieved for each match.\n\n"
            f"Specifically, verify if the analysis contains any statements indicating that info is missing, "
            f"unavailable, unknown, or not found (e.g., 'no odds found', 'injuries not available', 'unknown form'). "
            f"If a match report contains such statements, mark `is_complete` as false for that match and explain what was missing "
            f"in `missing_details_summary`.\n\n"
            f"Here is the list of matches you must validate:\n"
            + "\n".join([f"- {m.home_team} vs {m.away_team}" for m in matches]) + "\n\n"
            f"--- COMBINED MATCH REPORT ---\n"
            f"{combined_report_str}"
        )
        
        config_validation = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ValidationResult,
        )
        
        try:
            validation_resp = generate_content_with_retry(
                client=client,
                model="gemini-2.5-flash",
                contents=validator_prompt,
                config=config_validation,
            )
            import json
            validation_data = json.loads(validation_resp.text)
            validation_result = ValidationResult(**validation_data)
            
            any_incomplete = False
            for res in validation_result.results:
                print(f"      • Match '{res.match_name}': Complete = {res.is_complete}")
                if not res.is_complete:
                    any_incomplete = True
                    print(f"        Reason: {res.missing_details_summary}")
                    
                    # Evict from match_analyses to trigger re-analysis in the next loop
                    if res.match_name in match_analyses:
                        del match_analyses[res.match_name]
                    match_missing_feedback[res.match_name] = res.missing_details_summary
            
            if not any_incomplete:
                print("   ✅ All match analyses are complete and valid!")
                break
                
        except Exception as e:
            print(f"   ⚠️ Error during validation step: {e}", file=sys.stderr)
            if pipeline_attempt == max_pipeline_attempts:
                raise RuntimeError(f"Validation step failed: {e}")
        
        pipeline_attempt += 1
        
    else:
        # If we exited the loop without breaking, we reached the max attempts and some matches are still incomplete.
        print("\n❌ CRITICAL: Incomplete information after maximum attempts.", file=sys.stderr)
        for m in matches:
            m_key = f"{m.home_team} vs {m.away_team}"
            if m_key not in match_analyses:
                feedback = match_missing_feedback.get(m_key, "Unknown details missing")
                print(f"   - Match '{m_key}' is still missing data: {feedback}", file=sys.stderr)
        raise RuntimeError("Pipeline terminated: Unable to retrieve complete information for all scheduled matches.")

    # Reconstruct the chronological list of individual analyses
    individual_analyses = []
    for idx, m in enumerate(matches, start=1):
        m_key = f"{m.home_team} vs {m.away_team}"
        individual_analyses.append(
            f"=========================================\n"
            f"MATCH {idx}: {m_key}\n"
            f"=========================================\n"
            f"{match_analyses[m_key]}\n"
        )
        
    matches_data_str = "\n".join(individual_analyses)
    print("\n   ✅ All matches analyzed and predicted successfully.")

    # ==========================================
    # Step 4: Create a summary
    # ==========================================
    hebrew_translation = config.get_hebrew_translation_setting()
    
    print("\n" + "-" * 60)
    if hebrew_translation:
        print("[Step 4] Creating Final Daily Summary (Hebrew)")
        instr_file = "summarize_day_he.md"
    else:
        print("[Step 4] Creating Final Daily Summary (English)")
        instr_file = "summarize_day_en.md"
    print("-" * 60)
    
    # Construct combined input for Step 4 containing both raw times from Step 1 and analysis text from Step 2/3
    combined_matches_data_list = []
    combined_matches_data_list.append("--- SCHEDULED MATCH TIMES ---")
    for match in matches:
        combined_matches_data_list.append(
            f"Match: {match.home_team} vs {match.away_team}\n"
            f"Israel Time: {match.match_time_israel}\n"
            f"Local Time: {match.match_time_local}\n"
        )
    combined_matches_data_list.append("--- MATCH ANALYSES AND PREDICTIONS ---")
    combined_matches_data_list.append(matches_data_str)
    combined_matches_data = "\n".join(combined_matches_data_list)

    run_hour_str = now_israel.strftime("%H:%M")
    try:
        summarize_instr = load_instruction(instr_file).format(
            date=today_str,
            matches_data=combined_matches_data,
            run_hour=run_hour_str
        )
    except Exception as e:
        print(f"❌ Error loading instruction file {instr_file}: {e}", file=sys.stderr)
        # Fallback to summarize_day.md
        summarize_instr = load_instruction("summarize_day.md").format(
            date=today_str,
            matches_data=combined_matches_data,
            run_hour=run_hour_str
        )
        hebrew_translation = True

    try:
        summary_resp = generate_content_with_retry(
            client=client,
            model=model_name,
            contents=summarize_instr,
        )
        final_summary = summary_resp.text
        if hebrew_translation:
            print("   ✅ Hebrew summary compiled successfully.")
        else:
            print("   ✅ English summary compiled successfully.")
    except Exception as e:
        print(f"   ❌ Error compiling summary: {e}", file=sys.stderr)
        raise e

    # Save summary to results folder
    output_file = config.RESULTS_DIR / f"{file_timestamp_str}.txt"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(final_summary)
        print(f"\n🎉 SUCCESS: Daily summary saved to: {output_file}")
    except Exception as e:
        print(f"❌ Error saving summary file: {e}", file=sys.stderr)
        raise e

    # Broadcast to Telegram
    try:
        post_to_telegram(final_summary)
    except Exception as e:
        print(f"❌ Error broadcasting to Telegram: {e}", file=sys.stderr)
        raise e
    print("=" * 60)

if __name__ == "__main__":
    run_pipeline()
