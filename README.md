# Football Analyst Agent ⚽🤖

An automated AI agent that tracks upcoming FIFA World Cup 2026 matches, performs real-time research, predicts outcomes, formats summaries for mobile screens, and broadcasts them to a Telegram channel.

The agent is powered by the **Google GenAI SDK** (utilizing `gemini-2.5-pro` with a rotation fallback chain of `gemini-2.5-flash` and `gemini-3.5-flash` protected by a 45-second client timeout) and leverages **Google Search Grounding** for real-time match data.

---

## 🌟 How the Agent Works
 
The agent runs in five sequential steps:
 
1. **Matchday Verification**: Checks if the current date is a scheduled World Cup 2026 matchday (June 11 to July 19, excluding rest days) to save API costs, unless overridden via `--force`.
2. **Daily Matches Retrieval**: Queries the **World Cup 2026 REST API (worldcup26.ir)** for upcoming matches. If it fails or returns no matches, the agent sequentially falls back to the **TheStatsAPI JSON API (thestatsapi.com)**, then to the **OpenFootball JSON API**, and finally to **Gemini Search Grounding** if all APIs fail.
3. **Match Research & Prediction**: Queries Google Search Grounding for each match to research team news, betting odds, injuries, suspensions, and tactical form, generating detailed previews and score predictions.
4. **Quality Validation & Correction**: All match analyses are combined and reviewed by an LLM-as-a-validator. If any match is missing critical details (e.g., odds or injuries), it is re-analyzed (up to three times) with targeted feedback injected into the prompt. If validation fails on the third attempt, the run aborts.
5. **Summary Compilation & Broadcast**: Compiles the final report, saves it to `results/`, and broadcasts it to the designated Telegram channel.
 
---
 
## 📂 Project Structure
 
```text
Football Analyst Agent/
├── .github/
│   └── workflows/
│       └── football_analyst.yml   # Workflow configuration (runs via API / external trigger)
├── results/
│   └── DD-MM-YY_HH-MM.txt         # Saved local text files
├── instructions/
│   ├── retrieve_games.md          # Step 2: LLM match retrieval template
│   ├── analyze_game.md            # Step 3: Search grounding template
│   ├── predict_game.md            # Step 3: Tipster prediction template
│   ├── summarize_day_he.md        # Step 5: Hebrew summarization instructions
│   └── summarize_day_en.md        # Step 5: English summarization instructions
├── src/
│   ├── agent.py                   # Main pipeline script
│   └── config.py                  # Settings loader and verification
├── .env_example.example           # Template for environment settings
├── config.json                    # Configuration for translation
├── requirements.txt               # Dependencies list
└── README.md                      # Project documentation
```

---

## ⚙️ Configuration & Environment

The agent reads configurations from a `.env` file for API keys, and a `config.json` file for translation options.

### 1. Environment Variables (`.env`)

Create a `.env` file in the root directory:

| Variable | Required | Description |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | **Yes** | Your API key from [Google AI Studio](https://aistudio.google.com/). |
| `TELEGRAM_BOT_TOKEN` | *Optional* | Telegram Bot token from `@BotFather`. |
| `TELEGRAM_CHAT_ID` | *Optional* | Target Telegram chat or channel ID. |

*Example `.env` content:*
```ini
GEMINI_API_KEY="AIzaSy..."
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
TELEGRAM_CHAT_ID="-100123456789"
```

### 2. General Configuration (`config.json`)

Control output language and date formatting:

```json
{
  "hebrew_translation": true
}
```

* **`hebrew_translation`**:
  * `true` (default): Output in Hebrew (using `summarize_day_he.md`) with `/` date separators (e.g. `14/06/26`).
  * `false`: Output in English (using `summarize_day_en.md`) with `-` date separators (e.g. `14-06-26`).

---

## 🚀 Local Setup & Execution

### Installation

1. **Clone & navigate** to the project directory:
   ```bash
   cd "Football Analyst Agent"
   ```
2. **Set up virtual environment**:
   * **Windows (PowerShell)**:
     ```powershell
     python -m venv .venv; .\.venv\Scripts\Activate.ps1
     ```
   * **macOS/Linux**:
     ```bash
     python -m venv .venv; source .venv/bin/activate
     ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure environment**:
   ```bash
   cp .env_example.example .env
   ```
   *Note: Open `.env` and fill in your API credentials.*

### Running the Pipeline

Run the agent normally:
```bash
python src/agent.py
```
> [!NOTE]
> On non-matchdays (rest days or outside the tournament window), the script exits in under a second to prevent unnecessary API calls and save costs.

To bypass matchday checks and force run (e.g., during testing):
```bash
python src/agent.py --force
```

---

## 🤖 GitHub Actions Automation

The agent is pre-configured to run automatically on World Cup matchdays. To bypass GitHub Actions cron delays, the workflow is designed to be triggered externally (e.g., via **cron-job.org**) using GitHub's REST API.

### 1. Configure GitHub Repository Secrets

Add the following secrets under **Settings > Secrets and variables > Actions > New repository secret**:
* `GEMINI_API_KEY`
* `TELEGRAM_BOT_TOKEN`
* `TELEGRAM_CHAT_ID`

> [!WARNING]
> **Telegram configuration is required for GitHub Actions.**
> Since GitHub Actions environments are ephemeral, local results in the `results/` folder are discarded when the run finishes. You must configure the Telegram credentials to receive and view the reports.

### 2. Setup External Scheduler (cron-job.org)

1. **Create a GitHub Personal Access Token (PAT)**:
   * Generate a token under **Settings > Developer Settings > Personal Access Tokens** with permissions to read/write **Actions** on this repository.
2. **Configure cron-job.org**:
   * Point the job to the GitHub API:
     `https://api.github.com/repos/itamarbarry/Football-Analyst-Agent/actions/workflows/football_analyst.yml/dispatches`
   * Set HTTP Method to **POST**.
   * Add headers:
     * `Authorization`: `Bearer YOUR_GITHUB_PAT`
     * `Accept`: `application/vnd.github.v3+json`
     * `User-Agent`: `cron-job-org`
   * Set Request Body to raw JSON:
     ```json
     { "ref": "main" }
     ```
