from dataclasses import dataclass


@dataclass
class SearchCriteria:
    city: str = "Bangalore"
    transaction_type: str = "Rent"
    property_category: str = "Flat"
    bhk: str = "3 BHK"
    budget_min: int = 50_000
    budget_max: int = 65_000
    min_floor: int = 10
    max_age_years: int = 5
    # Set higher than the total inventory so the scan doesn't stop early —
    # it will naturally end when it runs out of new listings to scroll to,
    # or hits collect_listings' own time/round safety caps.
    target_count: int = 3000


BASE_URL = "https://www.magicbricks.com"
OUTPUT_DIR = "output"
LINKS_FILE = f"{OUTPUT_DIR}/listing_links.txt"
LISTINGS_JSON = f"{OUTPUT_DIR}/listings.json"
REPORT_FILE = f"{OUTPUT_DIR}/recommendation_report.md"
