"""
Recovery script: generates a recommendation report from whatever is
currently saved in output/listings.json, without touching the browser.

Use this if agent.py's run was killed outright (process crash, forced
shutdown, terminal closed) before it reached its own analysis step.
collect_listings() saves progress to output/listings.json after every
match, so this can be run at any time to see the best pick from
whatever was scraped so far.

Run:
    python analyze_partial.py
"""
import json

from dotenv import load_dotenv

from config import LISTINGS_JSON, REPORT_FILE
from llm_analysis import analyze_listings

load_dotenv()


def main():
    with open(LISTINGS_JSON) as f:
        listings = json.load(f)

    print(f"Found {len(listings)} listings saved in {LISTINGS_JSON}.")
    if not listings:
        print("Nothing to analyze yet.")
        return

    report = analyze_listings(listings)
    with open(REPORT_FILE, "w") as f:
        f.write(report)

    print(f"Report saved to {REPORT_FILE}\n")
    print(report)


if __name__ == "__main__":
    main()
