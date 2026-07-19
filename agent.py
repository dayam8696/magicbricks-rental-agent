"""
LangGraph agent that drives Magicbricks at the UI level (via Playwright)
to find rental 3BHK flats matching SearchCriteria, then asks Gemini to
recommend the top 3 / best property.

Run:
    python agent.py
"""
import json
import os
import time
from typing import Optional, TypedDict

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

import browser_actions as ba
from config import SearchCriteria, LINKS_FILE, LISTINGS_JSON, REPORT_FILE, OUTPUT_DIR
from llm_analysis import analyze_listings

load_dotenv()


class AgentState(TypedDict, total=False):
    criteria: SearchCriteria
    playwright: object
    browser: object
    page: object
    listings: list[dict]
    report: str
    error: Optional[str]


# Tracks the active browser session outside of graph state, so a crash that
# happens before a node returns doesn't leak an unclosed Chromium process.
_current_session: dict = {}


def node_launch_browser(state: AgentState) -> AgentState:
    headful = os.environ.get("HEADFUL", "true").lower() == "true"
    playwright, browser, page = ba.launch_browser(headful=headful)
    ba.open_site(page)
    _current_session["playwright"] = playwright
    _current_session["browser"] = browser
    return {"playwright": playwright, "browser": browser, "page": page}


def node_select_city(state: AgentState) -> AgentState:
    ba.select_city(state["page"], state["criteria"].city)
    return {}


def node_select_transaction_type(state: AgentState) -> AgentState:
    ba.select_transaction_type(state["page"], state["criteria"].transaction_type)
    return {}


def node_select_property_type(state: AgentState) -> AgentState:
    ba.select_property_type(state["page"], state["criteria"].property_category, state["criteria"].bhk)
    return {}


def node_search(state: AgentState) -> AgentState:
    ba.click_search(state["page"])
    return {}


def node_set_budget(state: AgentState) -> AgentState:
    c = state["criteria"]
    ba.set_budget(state["page"], c.budget_min, c.budget_max)
    return {}


def _run_search_setup(page, criteria: SearchCriteria):
    """Re-fills the search form from scratch — used when resuming after a browser relaunch."""
    ba.open_site(page)
    ba.select_city(page, criteria.city)
    ba.select_transaction_type(page, criteria.transaction_type)
    ba.select_property_type(page, criteria.property_category, criteria.bhk)
    ba.set_budget(page, criteria.budget_min, criteria.budget_max)
    ba.click_search(page)
    page.wait_for_timeout(2000)


def node_collect_listings(state: AgentState, max_attempts: int = 15, overall_budget_seconds: int = 3 * 3600) -> AgentState:
    """
    If a long scan stalls (site throttling, browser crash), relaunch a fresh
    browser and resume on top of what's already collected, up to
    `max_attempts` restarts or `overall_budget_seconds` total.
    """
    criteria = state["criteria"]
    page, browser, playwright = state["page"], state["browser"], state["playwright"]
    headful = os.environ.get("HEADFUL", "true").lower() == "true"

    collected: list[dict] = []
    if os.path.exists(LISTINGS_JSON):
        try:
            with open(LISTINGS_JSON) as f:
                collected = json.load(f)
        except Exception:
            collected = []

    start = time.time()
    for attempt in range(1, max_attempts + 1):
        collected = ba.collect_listings(page, criteria, initial_collected=collected)

        if len(collected) >= criteria.target_count:
            break
        if attempt == max_attempts or time.time() - start > overall_budget_seconds:
            break

        print(f"\nScan stalled at {len(collected)} listings (attempt {attempt}/{max_attempts}). "
              f"Relaunching the browser and resuming...\n")
        try:
            browser.close()
            playwright.stop()
        except Exception:
            pass
        playwright, browser, page = ba.launch_browser(headful=headful)
        _run_search_setup(page, criteria)

    return {"listings": collected, "page": page, "browser": browser, "playwright": playwright}


def node_save_links(state: AgentState) -> AgentState:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(LINKS_FILE, "w") as f:
        for item in state["listings"]:
            f.write(item["link"] + "\n")
    with open(LISTINGS_JSON, "w") as f:
        json.dump(state["listings"], f, indent=2)
    return {}


def node_analyze(state: AgentState) -> AgentState:
    if not state["listings"]:
        return {"report": "No listings matched the given criteria. Try relaxing filters."}
    report = analyze_listings(state["listings"])
    with open(REPORT_FILE, "w") as f:
        f.write(report)
    return {"report": report}


def node_close_browser(state: AgentState) -> AgentState:
    try:
        state["browser"].close()
        state["playwright"].stop()
    except Exception:
        pass
    _current_session.clear()
    return {}


def _close_current_session():
    """Best-effort cleanup of whatever browser session is tracked, used when
    a retry attempt is about to relaunch a fresh one."""
    try:
        if "browser" in _current_session:
            _current_session["browser"].close()
        if "playwright" in _current_session:
            _current_session["playwright"].stop()
    except Exception:
        pass
    _current_session.clear()


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("launch_browser", node_launch_browser)
    graph.add_node("select_city", node_select_city)
    graph.add_node("select_transaction_type", node_select_transaction_type)
    graph.add_node("select_property_type", node_select_property_type)
    graph.add_node("search", node_search)
    graph.add_node("set_budget", node_set_budget)
    graph.add_node("collect_listings", node_collect_listings)
    graph.add_node("save_links", node_save_links)
    graph.add_node("analyze", node_analyze)
    graph.add_node("close_browser", node_close_browser)

    graph.add_edge(START, "launch_browser")
    graph.add_edge("launch_browser", "select_city")
    graph.add_edge("select_city", "select_transaction_type")
    graph.add_edge("select_transaction_type", "select_property_type")
    graph.add_edge("select_property_type", "set_budget")
    graph.add_edge("set_budget", "search")
    graph.add_edge("search", "collect_listings")
    graph.add_edge("collect_listings", "save_links")
    graph.add_edge("save_links", "analyze")
    graph.add_edge("analyze", "close_browser")
    graph.add_edge("close_browser", END)

    return graph.compile()


def _load_saved_listings() -> list[dict]:
    if not os.path.exists(LISTINGS_JSON):
        return []
    try:
        with open(LISTINGS_JSON) as f:
            return json.load(f)
    except Exception:
        return []


def main(max_attempts: int = 30, overall_budget_seconds: int = 3 * 3600):
    """
    Retries the entire graph run on any failure (a crash can happen at any
    node, not just while collecting listings), resuming from
    output/listings.json rather than losing progress. Whatever has been
    collected when attempts or the time budget run out still gets analyzed
    and reported.
    """
    app = build_graph()
    criteria = SearchCriteria()
    final_state: AgentState = {}
    start = time.time()

    for attempt in range(1, max_attempts + 1):
        try:
            final_state = app.invoke({"criteria": criteria})
            break  # reached close_browser node — a clean run
        except Exception as e:
            collected_so_far = len(_load_saved_listings())
            print(f"\nRun attempt {attempt}/{max_attempts} crashed ({type(e).__name__}: {e}). "
                  f"{collected_so_far} listings saved so far — restarting the browser...\n")
            _close_current_session()
            if time.time() - start > overall_budget_seconds:
                print("Overall time budget exhausted; stopping retries.")
                break

    listings = final_state.get("listings") or _load_saved_listings()
    report = final_state.get("report")
    if report is None:
        # Every attempt crashed before reaching node_analyze — generate the
        # report directly from whatever ended up saved to disk.
        report = analyze_listings(listings) if listings else "No listings matched the given criteria. Try relaxing filters."
        with open(REPORT_FILE, "w") as f:
            f.write(report)

    print(f"\nCollected {len(listings)} matching listings.")
    print(f"Links saved to {LINKS_FILE}")
    print(f"Full report saved to {REPORT_FILE}\n")
    print(report)


if __name__ == "__main__":
    main()
