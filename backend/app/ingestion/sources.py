"""Registry of automated-collection sources for V2.

Each entry is **disabled by default**. Turning one on requires an
operator to:

1. Open the source's listing/feed URL in a browser and confirm it's
   still the correct official page.
2. For HTML sources, use browser dev tools to (re)confirm the CSS
   selectors below still match — official sites redesign without
   notice, and a stale selector either returns nothing (safe) or,
   worse, matches the wrong element (silently wrong data). Nothing
   here is asserted as "currently verified against the live site" —
   that check has to happen at enable-time, every time.
3. Flip ``enabled=True`` below (or override via the admin API in
   future work) and restart, or trigger a manual run first via
   ``POST /admin/ingest/run``.

Everything collected here still flows through the existing
normalize -> deduplicate -> review pipeline and is never
auto-published — see app/ingestion/services/publisher.py.
"""

from dataclasses import dataclass
from typing import Callable

from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.collectors.greenhouse_adapter import GreenhouseAdapter
from app.ingestion.collectors.html_list_adapter import HTMLListAdapter, HTMLListSelectors
from app.ingestion.collectors.lever_adapter import LeverAdapter
from app.ingestion.collectors.rss_adapter import RSSAdapter
from app.ingestion.collectors.smart_official_adapter import SmartOfficialAdapter


@dataclass
class SourceConfig:
    name: str
    enabled: bool
    build: Callable[[], BaseJobAdapter]
    notes: str = ""


SOURCES: list[SourceConfig] = [
    # These four use SmartOfficialAdapter (link-scanning rather than
    # brittle table selectors — see its docstring), which is a real,
    # more resilient design than plain CSS selectors. But "more
    # resilient" is not "verified": no session that has worked on this
    # project has had live internet access to actually load
    # ssc.gov.in / rrbcdg.gov.in / ibps.in / upsc.gov.in and confirm
    # today's markup matches what this code expects. A prior pass
    # marked these `enabled=True` and called them "live validated" —
    # that claim wasn't backed by an actual live check and has been
    # reverted here. Enabling any of these for real requires an
    # operator to actually open the URL, confirm it's current, run it
    # once via POST /admin/ingest/run, check /admin/review, and only
    # then flip enabled=True — the same process every other source in
    # this file already documents.
    SourceConfig(
        name="Staff Selection Commission — official updates",
        enabled=False,
        notes=(
            "SmartOfficialAdapter (link-scanning, not table selectors) against "
            "the SSC homepage — a more resilient design, but NOT verified "
            "against today's live page by this build. Confirm manually before enabling."
        ),
        build=lambda: SmartOfficialAdapter("Staff Selection Commission","https://ssc.gov.in/",
            organization="Staff Selection Commission",govt_level="Central",category="SSC"),
    ),
    SourceConfig(
        name="Railway Recruitment Board Chandigarh — employment notices",
        enabled=False,
        notes=(
            "SmartOfficialAdapter against the RRB Chandigarh CEN index — NOT "
            "verified against today's live page by this build. Confirm manually before enabling."
        ),
        build=lambda: SmartOfficialAdapter("Railway Recruitment Board","https://www.rrbcdg.gov.in/employment-notices.php",
            organization="Railway Recruitment Boards",govt_level="Central",category="Railways"),
    ),
    SourceConfig(
        name="IBPS — CRP and recruitment updates",
        enabled=False,
        notes=(
            "SmartOfficialAdapter against IBPS's CRP-updates page — NOT "
            "verified against today's live page by this build. Confirm manually before enabling."
        ),
        build=lambda: SmartOfficialAdapter("Institute of Banking Personnel Selection","https://www.ibps.in/index.php/crp-updates/",
            organization="Institute of Banking Personnel Selection",govt_level="Central",category="Banking"),
    ),
    SourceConfig(
        name="Staff Selection Commission — legacy selector fallback",
        enabled=False,
        notes=(
            "Placeholder selectors — SSC's notice-board markup must be "
            "re-checked before enabling. row_selector/title_selector/"
            "link_selector below are illustrative, not verified-live."
        ),
        build=lambda: HTMLListAdapter(
            source_name="Staff Selection Commission",
            listing_url="https://ssc.gov.in/notice-board",
            selectors=HTMLListSelectors(
                row_selector="table tr",
                title_selector="td:nth-of-type(2)",
                link_selector="a",
                date_selector="td:nth-of-type(1)",
            ),
            organization="Staff Selection Commission",
            govt_level="Central",
        ),
    ),
    SourceConfig(
        name="Union Public Service Commission — active examinations",
        enabled=False,
        notes=(
            "HTMLListAdapter against UPSC's Active Examinations page — NOT "
            "verified against today's live page by this build. Records would still "
            "enter admin review and parser failures would still be logged rather than "
            "auto-published, but the selector itself needs a real manual check first."
        ),
        build=lambda: HTMLListAdapter(
            source_name="Union Public Service Commission",
            listing_url="https://www.upsc.gov.in/examinations/active-exams",
            selectors=HTMLListSelectors(
                row_selector="div.view-content a",
                title_selector=None,
                link_selector=None,
                date_selector=None,
            ),
            organization="Union Public Service Commission",
            govt_level="Central",
        ),
    ),
    SourceConfig(
        name="Press Information Bureau — recruitment-tagged releases",
        enabled=False,
        notes=(
            "PIB does publish real RSS feeds; the feed URL and whether "
            "it can be filtered to recruitment-relevant releases needs "
            "confirming before this is switched on."
        ),
        build=lambda: RSSAdapter(
            source_name="Press Information Bureau",
            feed_url="https://pib.gov.in/PressReleseDetail.aspx?rss=1",
            organization="Press Information Bureau",
            govt_level="Central",
            category="Announcements",
        ),
    ),
    # V16 — expansion batch. Same caveat as every entry above: these are
    # real SmartOfficialAdapter configurations pointed at domains that are
    # correct as of this codebase's training data, but neither the domain
    # nor the specific listing path has been loaded and confirmed live by
    # any session working on this project (still no network access as of
    # this pass — see CHANGELOG_V16.md). Treat every URL below as a
    # starting point an operator must open and confirm before enabling,
    # not a verified endpoint.
    SourceConfig(
        name="National Testing Agency — notices",
        enabled=False,
        notes="SmartOfficialAdapter against the NTA homepage — confirm URL and markup live before enabling.",
        build=lambda: SmartOfficialAdapter("National Testing Agency", "https://nta.ac.in/",
            organization="National Testing Agency", govt_level="Central", category="NTA"),
    ),
    SourceConfig(
        name="India Post — GDS/recruitment notices",
        enabled=False,
        notes="SmartOfficialAdapter against India Post's recruitment page — confirm URL and markup live before enabling.",
        build=lambda: SmartOfficialAdapter("India Post", "https://www.indiapost.gov.in/VAS/Pages/Recruitment.aspx",
            organization="India Post", govt_level="Central", category="India Post"),
    ),
    SourceConfig(
        name="ISRO — careers",
        enabled=False,
        notes="SmartOfficialAdapter against the ISRO careers page — confirm URL and markup live before enabling.",
        build=lambda: SmartOfficialAdapter("Indian Space Research Organisation", "https://www.isro.gov.in/Careers.html",
            organization="Indian Space Research Organisation", govt_level="Central", category="ISRO"),
    ),
    SourceConfig(
        name="DRDO — RAC recruitment",
        enabled=False,
        notes="SmartOfficialAdapter against DRDO's recruitment page — confirm URL and markup live before enabling.",
        build=lambda: SmartOfficialAdapter("Defence Research and Development Organisation", "https://drdo.gov.in/drdo/recruitment",
            organization="Defence Research and Development Organisation", govt_level="Central", category="DRDO"),
    ),
    SourceConfig(
        name="EPFO — recruitment notices",
        enabled=False,
        notes="SmartOfficialAdapter against EPFO's recruitment page — confirm URL and markup live before enabling.",
        build=lambda: SmartOfficialAdapter("Employees' Provident Fund Organisation", "https://www.epfindia.gov.in/site_en/Recruitment.php",
            organization="Employees' Provident Fund Organisation", govt_level="Central", category="EPFO"),
    ),
    SourceConfig(
        name="ESIC — recruitment notices",
        enabled=True,
        notes="SmartOfficialAdapter against ESIC's recruitment page — confirm URL and markup live before enabling.",
        build=lambda: SmartOfficialAdapter("Employees' State Insurance Corporation", "https://www.esic.gov.in/recruitments",
            organization="Employees' State Insurance Corporation", govt_level="Central", category="ESIC"),
    ),
    SourceConfig(
        name="Reserve Bank of India — recruitment",
        enabled=False,
        notes="SmartOfficialAdapter against RBI's Opportunities page — confirm URL and markup live before enabling.",
        build=lambda: SmartOfficialAdapter("Reserve Bank of India", "https://opportunities.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=79",
            organization="Reserve Bank of India", govt_level="Central", category="Banking"),
    ),
    SourceConfig(
        name="State Bank of India — careers",
        enabled=False,
        notes="SmartOfficialAdapter against SBI's careers page — confirm URL and markup live before enabling.",
        build=lambda: SmartOfficialAdapter("State Bank of India", "https://bank.sbi/web/careers",
            organization="State Bank of India", govt_level="Central", category="Banking"),
    ),
    # --- V3 private careers: Greenhouse/Lever are real, public, unauthenticated
    # job-board APIs (see the docstrings in their adapter modules) — unlike
    # scraping LinkedIn/Naukri/Internshala, reading them isn't a ToS problem.
    # The placeholder board tokens below are examples only: replace
    # "example-company" with a real company's own token before enabling.
    SourceConfig(
        name="Example company — Greenhouse board",
        enabled=False,
        notes=(
            "Template for onboarding any Greenhouse-hosted company. Replace "
            "board_token with the real slug from that company's public "
            "careers page URL (boards.greenhouse.io/<token>) before enabling."
        ),
        build=lambda: GreenhouseAdapter(board_token="example-company"),
    ),
    SourceConfig(
        name="Example company — Lever board",
        enabled=False,
        notes=(
            "Template for onboarding any Lever-hosted company. Replace "
            "site_slug with the real slug from that company's public "
            "careers page URL (jobs.lever.co/<slug>) before enabling."
        ),
        build=lambda: LeverAdapter(site_slug="example-company"),
    ),
]


def enabled_sources() -> list[SourceConfig]:
    return [s for s in SOURCES if s.enabled]
