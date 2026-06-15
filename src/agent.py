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
    
    # Try retrieving from the free REST API first
    try:
        print("   🔄 Connecting to World Cup 2026 REST API...")
        matches = retrieve_matches_via_api(now_israel)
        print("   ✅ API Call Successful!")
    except Exception as e:
        print(f"   ⚠️ API Call Failed ({e}).")
        print("   🔄 Falling back to Gemini search grounding for match retrieval...")
        
        retrieve_instr = load_instruction("retrieve_games.md").format(current_datetime=now_israel_str)
        # Enable search grounding for match retrieval fallback
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config_retrieval = types.GenerateContentConfig(
            tools=[grounding_tool],
            response_mime_type="application/json",
            response_schema=MatchList,
        )

        try:
            response = generate_content_with_retry(
                client=client,
                model=model_name,
                contents=retrieve_instr,
                config=config_retrieval,
            )
            match_list: MatchList = response.parsed
            if match_list and match_list.matches:
                matches = match_list.matches
            print("   ✅ Fallback Gemini Search Retrieval Successful!")
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
    
    analyze_instr_template = load_instruction("analyze_game.md")
    predict_instr_template = load_instruction("predict_game.md")
    grounding_tool = types.Tool(google_search=types.GoogleSearch())

    individual_analyses = []
    
    for i, match in enumerate(matches, start=1):
        print(f"\n   🔍 [{i}/{len(matches)}] Analyzing and predicting {match.home_team} vs {match.away_team}...")
        
        match_prompt = (
            f"You are a professional football analyst and tipster. Your task is to perform web research "
            f"and make scoreline/winner predictions for the upcoming match:\n\n"
            f"Match: {match.home_team} vs {match.away_team}\n"
            f"Scheduled Time (Israel Time): {match.match_time_israel}\n"
            f"Scheduled Time (Local Time): {match.match_time_local}\n\n"
            f"--- RESEARCH GUIDELINES ---\n"
            f"{analyze_instr_template.format(home_team=match.home_team, away_team=match.away_team, date=today_str)}\n\n"
            f"--- PREDICTION GUIDELINES ---\n"
            f"{predict_instr_template.format(home_team=match.home_team, away_team=match.away_team, analysis_context='(Use your research findings to predict)')}"
        )
        
        try:
            config_analysis = types.GenerateContentConfig(tools=[grounding_tool])
            analysis_resp = generate_content_with_retry(
                client=client,
                model=model_name,
                contents=match_prompt,
                config=config_analysis,
            )
            match_analysis_text = analysis_resp.text
            print(f"      ✅ Match analyzed successfully.")
        except Exception as e:
            print(f"      ❌ Error during analysis of {match.home_team} vs {match.away_team}: {e}", file=sys.stderr)
            raise e
            
        individual_analyses.append(
            f"=========================================\n"
            f"MATCH {i}: {match.home_team} vs {match.away_team}\n"
            f"=========================================\n"
            f"{match_analysis_text}\n"
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
