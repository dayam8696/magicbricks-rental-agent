"""Send the scraped listings to Gemini and ask it to recommend the top 3 and the single best property."""
import json
import os

from google import genai
from google.genai.errors import APIError


def analyze_listings(listings: list[dict]) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in.")

    client = genai.Client(api_key=api_key)

    prompt = f"""You are a real-estate analyst. Below are {len(listings)} rental listings
in Bangalore (3BHK flats, floor above 10, budget 50,000-65,000 INR/month, less than
5 years old), scraped from Magicbricks.

Listings (JSON):
{json.dumps(listings, indent=2)}

Task:
1. Recommend the Top 3 properties, ranked, with a one-line reason each (consider
   price value, floor height, and age).
2. Call out the single Best property overall and explain why in 2-3 sentences.
3. Reference each recommended property by its `link` so the user can click through.

Respond in markdown."""

    try:
        response = client.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
        return response.text
    except APIError as e:
        return _fallback_report(listings, e)


def _fallback_report(listings: list[dict], error: Exception) -> str:
    """
    Gemini call failed (e.g. quota exhausted) — produce a plain report ranked by
    floor height (desc) then age (asc) so the run still ends with something useful
    instead of crashing.
    """
    ranked = sorted(listings, key=lambda l: (-l["floor"], l["age_years"]))
    top3 = ranked[:3]

    lines = [
        "# Listings Report (LLM analysis unavailable)",
        "",
        f"_Gemini call failed, falling back to a plain ranking. Error: {error}_",
        "",
        "## Top 3 (ranked by highest floor, then lowest age)",
        "",
    ]
    for i, item in enumerate(top3, 1):
        lines.append(
            f"{i}. Floor {item['floor']}, {item['age_years']} yrs old, {item['price']} — [{item['link']}]({item['link']})"
        )

    if ranked:
        best = ranked[0]
        lines += [
            "",
            "## Best overall",
            f"[{best['link']}]({best['link']}) — floor {best['floor']}, {best['age_years']} yrs old, {best['price']}.",
        ]

    return "\n".join(lines)
