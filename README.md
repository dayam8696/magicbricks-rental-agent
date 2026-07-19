# Magicbricks Rental Property Finder

A LangGraph-based automation agent that searches Magicbricks for rental flats
matching a set of criteria and uses Gemini to recommend the best options.

## How it works

The agent drives a real Chromium browser (via Playwright) the same way a
person would — clicking, typing, and scrolling on magicbricks.com. No
Magicbricks API is used.

1. Fills in the search form: city, Rent/Buy, property type, BHK, and budget.
2. Scrolls through the results (Magicbricks loads more listings via infinite
   scroll rather than numbered pages).
3. For each listing above the configured floor, opens its individual detail
   page to read the authoritative construction age — this field is rarely
   shown on the summary card, so the detail page is the reliable source.
4. Keeps every listing that matches all criteria, saving progress to disk
   after each one.
5. Sends the shortlist to Gemini, which returns a ranked Top 3 and picks the
   single best property.

## Tech stack

- **Python 3**
- **Playwright** — browser automation
- **LangGraph** — orchestrates the search as a state graph
- **Google Gemini** (`google-genai`) — ranks the shortlisted properties
- **python-dotenv** — loads the Gemini API key from `.env`

## Setup

```bash
cd magicbricks_agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # then fill in GEMINI_API_KEY
```

## Configuration

Edit `config.py` to change what the agent searches for — city, transaction
type (Rent/Buy), property type, BHK, budget range, minimum floor, maximum
construction age, and how many matching listings to collect.

## Running it

```bash
python agent.py
```

For a long run, use the supervised launcher instead. It keeps the display
awake and automatically restarts the browser if a session stalls or
crashes, without losing any progress already made:

```bash
./run_supervised.sh
```

Set `HEADFUL=false` in `.env` to run without a visible browser window.

## Output

Everything is written to the `output/` folder:

| File | Contents |
|---|---|
| `output/recommendation_report.md` | **The final report** — Gemini's Top 3 and best-overall recommendation |
| `output/listings.json` | Full data for every matching listing (floor, age, price, link) |
| `output/listing_links.txt` | Just the links, one per line |

Progress is saved to `output/listings.json` after every match, so a run can
be stopped and resumed at any time — the next run continues from there
instead of starting over.

If a run stops before reaching the analysis step, generate the report from
whatever was already collected without re-scraping:

```bash
python analyze_partial.py
```

## Files

| File | Purpose |
|---|---|
| `agent.py` | LangGraph state machine wiring the steps together, with retry/resume logic |
| `browser_actions.py` | Playwright functions, one per UI step |
| `llm_analysis.py` | Builds the prompt and calls Gemini for the recommendation |
| `config.py` | Search criteria — edit this to reuse the agent for a different search |
| `analyze_partial.py` | Regenerates the report from `output/listings.json` without re-scraping |
| `run_supervised.sh` | Watchdog wrapper that restarts `agent.py` automatically on a stall |
