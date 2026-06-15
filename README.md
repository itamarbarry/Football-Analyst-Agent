# Football Analyst Agent ⚽🤖

An automated AI agent that tracks upcoming FIFA World Cup 2026 matches, performs real-time research, predicts outcomes, formats summaries for mobile screens, and broadcasts them to a Telegram channel.

The agent is powered by the new **Google GenAI SDK** (utilizing `gemini-2.5-pro` as primary, with a rotation fallback chain of `gemini-2.5-flash` and `gemini-3.5-flash` protected by a 45-second client timeout) and leverages **Google Search Grounding** to retrieve up-to-date data on odds, injuries, lineups, and team form.

---

## 🌟 How the Agent Works

The agent operates as an autonomous football analyst, continuously monitoring upcoming World Cup fixtures. Each day, it searches the web to identify all matches scheduled to be played within the next 24 hours.

For every upcoming match, the agent performs extensive research across multiple online sources, gathering key information such as current betting odds, recent team form, player injuries and suspensions, head-to-head statistics, and insights from football experts and analysts.

Using this information, the agent evaluates each matchup and generates its own scoreline and winner predictions. The results are then automatically formatted into a mobile-friendly report and published directly to a Telegram channel.

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
│   ├── retrieve_games.md          # Step 1: LLM match retrieval template
│   ├── analyze_game.md            # Step 2: Search grounding template
│   ├── predict_game.md            # Step 3: Tipster prediction template
│   ├── summarize_day_he.md        # Step 4: Hebrew summarization instructions
│   └── summarize_day_en.md        # Step 4: English summarization instructions
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

The agent reads configurations from two sources: a `.env` file for API keys, and a `config.json` file for workflow options.

### 1. Environment Variables (`.env`)

Create a `.env` file in the root directory. It supports the following variables:

| Variable | Required | Description |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | **Yes** | Your API key from [Google AI Studio](https://aistudio.google.com/). Used to run predictions and search grounding. |
| `TELEGRAM_BOT_TOKEN` | *Optional* | The token for your Telegram Bot from `@BotFather`. |
| `TELEGRAM_CHAT_ID` | *Optional* | The chat ID (or channel username/ID) where the bot will post daily summaries. |

*Example `.env` content:*
```ini
GEMINI_API_KEY="AIzaSy..."
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
TELEGRAM_CHAT_ID="-100123456789"
```

### 2. General Configuration (`config.json`)

You can control output localization by editing the `config.json` file in the project root:

```json
{
  "hebrew_translation": true
}
```

* **`hebrew_translation`**:
  * `true` (default): Output will be written and formatted in Hebrew (using `instructions/summarize_day_he.md`) and date separators will be `/` (e.g. `14/06/26`).
  * `false`: Output will be written in English (using `instructions/summarize_day_en.md`) and date separators will be `-` (e.g. `14-06-26`).

---

## 🚀 Local Setup & Execution

### Installation

1. **Clone the repository** and navigate to the project directory:
   ```bash
   cd "Football Analyst Agent"
   ```

2. **Create and activate a virtual environment**:
   * **Windows (PowerShell)**:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   * **macOS/Linux**:
     ```bash
     python -m venv .venv
     source .venv/bin/activate
     ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Setup environment variables**:
   Create a `.env` file by copying the example template:
   ```bash
   cp .env.example .env
   ```
   Open the `.env` file and insert your API keys.

### Running the Pipeline

To run the agent locally:
```bash
python src/agent.py
```
This triggers the 4-step execution flow:
1. **Connects to REST API** (or falls back to Gemini grounding) to find games for the next 24 hours.
2. **Performs web searches** for injuries, form, tactical updates, and betting odds.
3. **Builds the daily summary** according to the selected language template, saves it to `results/` (as a `.txt` file), and broadcasts it to Telegram.

---

## 🤖 GitHub Actions Automation

The agent is pre-configured to run automatically on World Cup matchdays using GitHub Actions. To ensure strict timing and bypass GitHub's native cron scheduling delays, we trigger the workflow externally (e.g. via **cron-job.org**) using GitHub's REST API.

### Setting up secrets:

1. Push this project to your GitHub Repository.
2. Go to your repository on GitHub.
3. Navigate to **Settings** > **Secrets and variables** > **Actions**.
4. Click on **New repository secret** and add:
   * `GEMINI_API_KEY`
   * `TELEGRAM_BOT_TOKEN` 
   * `TELEGRAM_CHAT_ID` 

> [!WARNING]
> **GitHub Actions & Telegram Broadcasts:**
> If you run the pipeline using GitHub Actions without configuring `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, you **will not be able to view the generated results**.
> Since GitHub Actions runner environments are temporary environments, the local text files saved to the `results/` directory are discarded when the workflow run finishes. To view the daily reports and match summaries when running via GitHub Actions, you must configure the Telegram API keys so they can be broadcast to your channel.

### Running with an External Scheduler (e.g., cron-job.org):
1. **Create a GitHub Personal Access Token (PAT):**
   * Go to **Settings > Developer Settings > Personal Access Tokens > Tokens (classic)** or **Fine-grained tokens**.
   * Generate a token with permissions to read/write **Actions** on this repository.
2. **Setup cron-job.org:**
   * Create a cron job pointing to the GitHub API (for example:
     `https://api.github.com/repos/itamarbarry/Football-Analyst-Agent/actions/workflows/football_analyst.yml/dispatches`)
   * Set HTTP Method to **POST**.
   * Pass headers:
     * `Authorization`: `Bearer YOUR_GITHUB_PAT`
     * `Accept`: `application/vnd.github.v3+json`
     * `User-Agent`: `cron-job-org`
   * Set Request Body to raw JSON:
     ```json
     { "ref": "main" }
     ```

### Matchday Awareness:
* If it's not a World Cup matchday (such as July 8, 11, 13, 16, 17, 18, or after the tournament ends on July 19), the script immediately logs a notification and exits cleanly in under a second without calling the Gemini API or sending a Telegram broadcast to save API costs.
