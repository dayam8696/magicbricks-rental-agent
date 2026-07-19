"""
UI-level browser actions for Magicbricks, built on Playwright.

Every function here drives the real page the way a human would: clicking
visible buttons, typing into visible inputs, reading rendered text off
listing cards. Nothing calls a Magicbricks API or endpoint directly.
"""
import json
import os
import re
import time
from typing import Optional

from playwright.sync_api import Page, sync_playwright, TimeoutError as PWTimeout

from config import SearchCriteria, BASE_URL, LISTINGS_JSON, LINKS_FILE, OUTPUT_DIR


def launch_browser(headful: bool = True):
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=not headful, slow_mo=150 if headful else 0)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    return playwright, browser, page


def open_site(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    _dismiss_popups(page)


def _dismiss_popups(page: Page):
    for text in ["Allow", "Not now", "No thanks", "close", "X"]:
        try:
            page.get_by_text(text, exact=False).first.click(timeout=1500)
        except Exception:
            pass


# Checkbox ids for the property-type / BHK filter panel on the search bar.
# Multiple boxes are checked by default (e.g. 2 & 3 BHK), so every box needs
# to be explicitly set on or off rather than just checking the target one.
BHK_CHECKBOX_IDS = {
    "1 BHK": "bhkFlatHouse_0",
    "2 BHK": "bhkFlatHouse_1",
    "3 BHK": "bhkFlatHouse_2",
    "4 BHK": "bhkFlatHouse_3",
    "5 BHK": "bhkFlatHouse_4",
}

PROPERTY_CHECKBOX_IDS = {
    "Flat": "residential_0",
    "House/Villa": "residential_1",
    "Plot": "residential_2",
}


def _robust_click(page: Page, locator, timeout: int = 5000):
    """
    Click a locator that may be intercepted by Magicbricks' sticky header
    (a fixed-position header subtree overlapping the target after scroll).
    Nudges scroll to clear the header, then falls back to a JS-dispatched
    click if a real pointer click still can't land.
    """
    locator.scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, -150)")
    try:
        locator.click(timeout=timeout)
    except Exception:
        # The click may have already landed and triggered navigation before
        # timing out (e.g. the Search button) — the element is now detached,
        # so the JS-dispatched fallback can itself fail. That's fine; there's
        # nothing more useful to try.
        try:
            locator.evaluate("el => el.click()")
        except Exception:
            pass


def _set_checkbox(page: Page, checkbox_id: str, desired: bool):
    checkbox = page.locator(f"#{checkbox_id}")
    if not checkbox.count():
        return
    if checkbox.is_checked() != desired:
        label = page.locator(f"label[for='{checkbox_id}']")
        if label.count():
            _robust_click(page, label)
        else:
            checkbox.click(force=True)


def select_city(page: Page, city: str):
    """
    Magicbricks defaults the homepage search to a city (often geo-IP based),
    reflected in hidden input#homeSearchTxt. If it already matches, there's
    nothing to click. Otherwise, best-effort: click the visible city-name
    element near the search bar and pick the target city from the dropdown.
    """
    current = page.locator("#homeSearchTxt").get_attribute("value") or ""
    if current.strip().lower() == city.strip().lower():
        return

    # Best-effort fallback if the default city doesn't match.
    city_selector = page.locator("[id*='city' i]:visible, [class*='city' i]:visible").first
    if city_selector.count():
        _robust_click(page, city_selector)
        _robust_click(page, page.get_by_text(city, exact=False).first, timeout=5000)


def select_transaction_type(page: Page, transaction_type: str):
    """
    e.g. 'Rent' vs 'Buy'. The search widget's own category tabs
    (#tabBUY / #tabRENT, inside .mb-search__tab) are what actually control
    the search — NOT the top-nav mega-menu links (#rentheading / #buyheading),
    which only open a hover dropdown and leave the search form on its
    default "Buy" category.
    """
    id_map = {"rent": "tabRENT", "buy": "tabBUY"}
    target_id = id_map.get(transaction_type.strip().lower())
    if target_id:
        el = page.locator(f"#{target_id}")
        if el.count():
            _robust_click(page, el.first)
            page.wait_for_timeout(1000)
            return
    _robust_click(page, page.get_by_text(transaction_type, exact=False).first)
    page.wait_for_timeout(1000)


def _open_property_type_dropdown(page: Page):
    """The property-type/BHK checkboxes are hidden in a collapsed dropdown; open it first."""
    trigger = page.locator("#buy_proertyTypeDefault")
    if not trigger.count():
        trigger = page.locator("[id*='propertyType' i]:visible").first

    _robust_click(page, trigger)
    page.wait_for_timeout(400)


def select_property_type(page: Page, category: str, bhk: str):
    """Ensure only `category` is checked among property types, and only `bhk` among BHK options."""
    _open_property_type_dropdown(page)

    for name, checkbox_id in PROPERTY_CHECKBOX_IDS.items():
        _set_checkbox(page, checkbox_id, desired=(name == category))

    for name, checkbox_id in BHK_CHECKBOX_IDS.items():
        _set_checkbox(page, checkbox_id, desired=(name == bhk))

    # Close the dropdown so it doesn't obscure the budget fields below it.
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


def _open_budget_dropdown(page: Page):
    """
    Budget min/max inputs are hidden inside a collapsed "Budget" dropdown,
    same pattern as the property-type panel. Confirmed trigger for the Rent
    tab: span#rent_budget_lbl (text "Budget").
    """
    for selector in ["#rent_budget_lbl", "#buy_budget_lbl", "[id$='_budget_lbl']"]:
        el = page.locator(selector)
        if el.count():
            _robust_click(page, el.first)
            page.wait_for_timeout(400)
            return


def set_budget(page: Page, budget_min: int, budget_max: int):
    """Budget fields live directly on the homepage search bar; fill them before hitting Search."""
    _open_budget_dropdown(page)

    min_input = page.locator("#budgetMin")
    max_input = page.locator("#budgetMax")
    if min_input.count() and budget_min:
        _robust_click(page, min_input)
        min_input.fill(str(budget_min))
    if max_input.count():
        _robust_click(page, max_input)
        max_input.fill(str(budget_max))
    page.keyboard.press("Tab")
    page.wait_for_timeout(500)

    # Close the dropdown so it doesn't obscure the Search button.
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


def click_search(page: Page):
    """
    Search-button selector not yet confirmed against the live DOM — trying a
    few likely candidates based on Magicbricks' 'mb-search__*' naming
    convention seen elsewhere on the page, with a text-based fallback.
    """
    candidates = [
        "button.mb-search__button",
        "a.mb-search__button",
        "[class*='mb-search__cta' i]",
        "[class*='mb-search__btn' i]",
        "button:has-text('Search')",
        "a:has-text('Search')",
    ]
    for selector in candidates:
        el = page.locator(selector)
        if el.count():
            _robust_click(page, el.first)
            break
    page.wait_for_load_state("domcontentloaded", timeout=30_000)
    page.wait_for_timeout(2000)


# Card text renders as "FLOOR\n5 out of 9" (label, then value, then total).
FLOOR_RE = re.compile(r"FLOOR\s*\n?\s*(Ground|Lower\s+Basement|Upper\s+Basement|\d+)\s*(?:st|nd|rd|th)?\s*out\s*of\s*\d+", re.I)

# Card descriptions sometimes mention "monthly maintenance is ₹X" before the
# actual rent, so the real price is anchored to the label that follows it
# (Security Deposit / per sqft / Request Callback) instead of the first ₹ match.
PRICE_RE = re.compile(r"₹\s*\n?([\d,]+)\s*\n(?:.{0,20})?(?:Security Deposit|per\s*sqft|Request Callback)", re.I)


def _parse_floor(text: str) -> Optional[int]:
    """Extracts the floor number from a search-results card. Ground/basement count as 0."""
    m = FLOOR_RE.search(text)
    if not m:
        return None
    value = m.group(1)
    return int(value) if value.isdigit() else 0


def _parse_construction_age_value(value: str) -> Optional[int]:
    """
    Parses the listing detail page's "Age of Construction" field, e.g.
    "Less than 5 years", "5 to 10 years", "10+ years", "New Launch",
    "Under Construction".
    """
    value = value.strip()
    m = re.match(r"Less\s*than\s*(\d+)\s*years?", value, re.I)
    if m:
        return max(int(m.group(1)) - 1, 0)
    if re.search(r"New\s*Launch|Under\s*Construction", value, re.I):
        return 0
    m = re.match(r"(\d+)\s*to\s*(\d+)\s*years?", value, re.I)
    if m:
        return int(m.group(2))
    m = re.match(r"(\d+)\+?\s*years?", value, re.I)
    if m:
        return int(m.group(1))
    return None


def _open_card_detail_page(page: Page, card) -> Optional[Page]:
    """
    A card's own <a> link (project/developer name) leads to a project
    overview page with no "Age of Construction" field. The individual
    listing's detail page only opens by clicking the card's title text,
    which navigates via JS into a new tab rather than a plain href.
    """
    title = card.locator("h2, .mb-srp__card--title, [class*='title' i]").first
    if not title.count():
        return None
    try:
        with page.context.expect_page(timeout=5000) as new_page_info:
            title.click()
        detail = new_page_info.value
        detail.wait_for_load_state("domcontentloaded", timeout=15000)
        detail.wait_for_timeout(1000)
        return detail
    except Exception:
        return None


def _close_extra_tabs(page: Page):
    """Closes every tab except the main search-results page — clicking a
    card's title can open extra ad/tracking tabs alongside the detail page."""
    for p in list(page.context.pages):
        if p is not page:
            try:
                p.close()
            except Exception:
                pass


def _extract_listing_details(detail: Page) -> dict:
    """Reads floor / construction age / rent from a listing's detail page."""
    result = {"floor": None, "age_years": None, "price": None, "url": detail.url}
    try:
        text = detail.inner_text("body")

        m = re.search(r"Floor\s*\n?\s*(\d+)\s*\(Out\s*of\s*\d+\s*Floors?\)", text, re.I)
        if m:
            result["floor"] = int(m.group(1))

        m = re.search(r"Age\s*of\s*Construction\s*\n?\s*([^\n]+)", text, re.I)
        if m:
            result["age_years"] = _parse_construction_age_value(m.group(1))

        m = re.search(r"Rental\s*Value\s*\n?\s*₹\s*([\d,]+)", text, re.I)
        if m:
            result["price"] = f"₹{m.group(1)}"
    except Exception:
        pass
    return result


def _save_progress(collected: list[dict]):
    """Writes progress to disk after every match, so a crash or manual stop never loses it."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(LISTINGS_JSON, "w") as f:
        json.dump(collected, f, indent=2)
    with open(LINKS_FILE, "w") as f:
        for item in collected:
            f.write(item["link"] + "\n")


def collect_listings(
    page: Page,
    criteria: SearchCriteria,
    max_rounds: int = 500,
    max_seconds: int = 10_800,
    max_detail_checks: int = 3000,
    initial_collected: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Results load via infinite scroll (no "Next" page control), so this keeps
    scrolling and scanning newly-appended cards until `target_count` matches
    are found, the page stops loading new cards, or the round/time caps hit.

    Two-stage filtering: floor is checked cheaply from the search-results
    card text first; only cards that clear it get their listing detail page
    opened to read the authoritative "Age of Construction" field, which is
    rarely present on the card itself.

    Resilient to interruption: progress is saved to disk after every match,
    and any error or Ctrl+C returns whatever has been collected so far
    instead of crashing. `initial_collected` lets a caller resume a previous
    scan without losing what it already found.
    """
    collected: list[dict] = list(initial_collected) if initial_collected else []
    seen_links: set[str] = {item["link"] for item in collected}
    cards = page.locator("div.mb-srp__card, div.SRCard, [data-testid='mb-srp-card']")
    scanned_count = 0
    no_growth_streak = 0
    detail_checks = 0
    consecutive_detail_failures = 0
    start = time.time()

    try:
        for _ in range(max_rounds):
            if len(collected) >= criteria.target_count:
                break
            if time.time() - start > max_seconds:
                break

            # The next batch loads via an async XHR after scrolling near the
            # bottom — a quick scroll-and-check reads a stale count and looks
            # like "no more results" when the page just hasn't finished loading
            # yet. Give it real dwell time and don't give up on a single stall.
            _lazy_scroll(page, steps=8)
            total_count = cards.count()
            if total_count <= scanned_count:
                no_growth_streak += 1
                if no_growth_streak >= 3:
                    break  # reached the actual end of the results
                continue
            no_growth_streak = 0

            stalled_on_detail_page = False
            for i in range(scanned_count, total_count):
                if len(collected) >= criteria.target_count:
                    break
                if time.time() - start > max_seconds:
                    break
                card = cards.nth(i)
                try:
                    card_text = card.inner_text(timeout=2000)
                except PWTimeout:
                    continue

                floor = _parse_floor(card_text)
                if floor is None or floor <= criteria.min_floor:
                    continue

                if detail_checks >= max_detail_checks:
                    continue
                detail_checks += 1

                detail = _open_card_detail_page(page, card)
                if detail is None:
                    _close_extra_tabs(page)
                    consecutive_detail_failures += 1
                    print(f"  [explored {detail_checks} | matched {len(collected)}] detail page failed to open, skipping")
                    # The site occasionally stops honoring the title-click
                    # (rapid tab open/close looking bot-like) — scrolling
                    # still works so this wouldn't otherwise be caught as
                    # "no more results". Treat a long failure streak as a
                    # stall so the caller can relaunch a fresh session.
                    if consecutive_detail_failures >= 15:
                        stalled_on_detail_page = True
                        break
                    continue
                consecutive_detail_failures = 0
                try:
                    details = _extract_listing_details(detail)
                finally:
                    _close_extra_tabs(page)

                href = details["url"]
                if href in seen_links:
                    continue
                seen_links.add(href)

                age_years = details["age_years"]
                if age_years is None or age_years >= criteria.max_age_years:
                    print(f"  [explored {detail_checks} | matched {len(collected)}] "
                          f"floor={floor} age={age_years} -> rejected, {href}")
                    continue

                price_match = PRICE_RE.search(card_text)
                collected.append(
                    {
                        "link": href,
                        "floor": details["floor"] or floor,
                        "age_years": age_years,
                        "price": details["price"] or (f"₹{price_match.group(1)}" if price_match else "N/A"),
                        "raw_text_snippet": card_text[:200].replace("\n", " "),
                    }
                )
                _save_progress(collected)
                print(f"  [explored {detail_checks} | matched {len(collected)}] "
                      f"floor={floor} age={age_years} -> MATCH, {href}")

            scanned_count = total_count
            if stalled_on_detail_page:
                print(f"\n{consecutive_detail_failures} detail pages in a row failed to open — "
                      f"the site is likely throttling this session. Stopping so the browser can restart.\n")
                break
    except (KeyboardInterrupt, Exception) as e:
        print(f"\nScan stopped early ({type(e).__name__}: {e}). "
              f"Proceeding with {len(collected)} listings collected so far.")

    return collected


def _lazy_scroll(page: Page, steps: int = 6):
    """Scrolls down, then waits for the site's own loading spinner (#pageLoader)
    to disappear so the next batch of cards has actually finished rendering."""
    for _ in range(steps):
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(400)
    try:
        page.locator("#pageLoader").wait_for(state="hidden", timeout=5000)
    except PWTimeout:
        pass
