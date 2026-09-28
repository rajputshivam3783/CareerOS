"""V19.2 — initial SourceRegistry entries for the named central
organizations.

Same policy as ``app/ingestion/sources.py`` (V2, unchanged) and
``app/ingestion/source_catalog.py``: every domain below is a
long-standing, well-known official domain, but **no session working
on this codebase has had live internet access to load it and confirm
today's markup/endpoint still matches** — so every row is seeded with
``status="disabled"``. An operator (via the admin Source dashboard or
``PATCH /government/sources/{id}`` with ``{"status": "active"}``)
must open the URL, confirm it's current, and run it once manually
before enabling it for real. Seeding a row is a catalog entry, not a
scraping permission — identical to the V19.1 policy already documented
in SOURCE_REGISTRY.md.

State-level bodies (State PSCs, State Police recruitment boards, State
High Courts, State Universities, State Health Recruitment Boards) are
**not** seeded here: there are ~29 states/UTs behind each category and
fabricating specific URLs this codebase has never loaded would be
exactly the "unofficial scraper" this framework is required to avoid.
Instead they're a documented *template* — see
docs/SOURCE_ADAPTER_ARCHITECTURE.md's "Adding a new organization"
section — an operator adds one row per state through the same
``POST /government/sources`` endpoint every other row here uses.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import SourceRegistry

# (source_name, official_url, organization, govt_level, category)
FRAMEWORK_ORGANIZATIONS: list[tuple[str, str, str, str, str]] = [
    ("Union Public Service Commission", "https://www.upsc.gov.in/", "Union Public Service Commission", "Central", "Civil Services"),
    ("Staff Selection Commission", "https://ssc.gov.in/", "Staff Selection Commission", "Central", "SSC"),
    ("Railway Recruitment Boards", "https://www.rrbcdg.gov.in/", "Railway Recruitment Boards", "Central", "Railways"),
    ("Institute of Banking Personnel Selection", "https://www.ibps.in/", "Institute of Banking Personnel Selection", "Central", "Banking"),
    ("State Bank of India", "https://bank.sbi/web/careers", "State Bank of India", "PSU", "Banking"),
    ("Reserve Bank of India", "https://opportunities.rbi.org.in/", "Reserve Bank of India", "Central", "Banking"),
    ("National Bank for Agriculture and Rural Development", "https://www.nabard.org/careers.aspx", "NABARD", "Central", "Banking"),
    ("Life Insurance Corporation of India", "https://licindia.in/careers", "Life Insurance Corporation of India", "PSU", "Insurance"),
    ("India Post", "https://www.indiapost.gov.in/VAS/Pages/Recruitment.aspx", "India Post", "Central", "India Post"),
    ("Defence Research and Development Organisation", "https://drdo.gov.in/drdo/recruitment", "Defence Research and Development Organisation", "Central", "DRDO"),
    ("Indian Space Research Organisation", "https://www.isro.gov.in/Careers.html", "Indian Space Research Organisation", "Central", "ISRO"),
    ("Bhabha Atomic Research Centre", "https://www.barc.gov.in/careers/", "Bhabha Atomic Research Centre", "Central", "BARC"),
    ("Nuclear Power Corporation of India Limited", "https://npcilcareers.co.in/", "Nuclear Power Corporation of India Limited", "PSU", "NPCIL"),
    ("National Testing Agency", "https://nta.ac.in/", "National Testing Agency", "Central", "NTA"),
    ("University Grants Commission", "https://www.ugc.gov.in/", "University Grants Commission", "Central", "UGC"),
    ("All India Institute of Medical Sciences", "https://aiimsexams.ac.in/", "All India Institute of Medical Sciences", "Central", "AIIMS"),
    ("Employees' State Insurance Corporation", "https://www.esic.gov.in/recruitments", "Employees' State Insurance Corporation", "Central", "ESIC"),
    ("Employees' Provident Fund Organisation", "https://www.epfindia.gov.in/site_en/Recruitment.php", "Employees' Provident Fund Organisation", "Central", "EPFO"),
    ("Food Corporation of India", "https://fci.gov.in/", "Food Corporation of India", "PSU", "FCI"),
    ("GAIL (India) Limited", "https://gailonline.com/careers.html", "GAIL (India) Limited", "PSU", "PSU — Energy"),
    ("Oil and Natural Gas Corporation", "https://ongcindia.com/web/eng/careers", "Oil and Natural Gas Corporation", "PSU", "PSU — Energy"),
    ("Indian Oil Corporation Limited", "https://iocl.com/careers", "Indian Oil Corporation Limited", "PSU", "PSU — Energy"),
    ("Hindustan Petroleum Corporation Limited", "https://www.hindustanpetroleum.com/careers", "Hindustan Petroleum Corporation Limited", "PSU", "PSU — Energy"),
    ("Bharat Petroleum Corporation Limited", "https://www.bharatpetroleum.in/careers.aspx", "Bharat Petroleum Corporation Limited", "PSU", "PSU — Energy"),
    ("Bharat Electronics Limited", "https://bel-india.in/Careers", "Bharat Electronics Limited", "PSU", "PSU — Defence"),
    ("Bharat Heavy Electricals Limited", "https://www.bhel.com/careers", "Bharat Heavy Electricals Limited", "PSU", "PSU — Engineering"),
    ("Hindustan Aeronautics Limited", "https://hal-india.co.in/Career", "Hindustan Aeronautics Limited", "PSU", "PSU — Defence"),
    ("Steel Authority of India Limited", "https://sailcareers.com/", "Steel Authority of India Limited", "PSU", "PSU — Steel"),
    ("Coal India Limited", "https://www.coalindia.in/career/", "Coal India Limited", "PSU", "PSU — Mining"),
    ("Power Grid Corporation of India Limited", "https://www.powergrid.in/en/careers", "Power Grid Corporation of India Limited", "PSU", "PSU — Power"),
]


def seed_framework_organizations(db: Session) -> dict:
    """Idempotent: inserts a disabled SourceRegistry row for every
    organization above that isn't already registered (by source_name).
    Safe to call repeatedly (e.g. from a migration follow-up script or
    an admin 'Seed framework organizations' button) — never updates or
    re-enables an existing row, so it can't clobber an operator's
    manual verification work."""
    existing_names = set(db.scalars(select(SourceRegistry.source_name)).all())
    created = []
    for source_name, url, organization, govt_level, category in FRAMEWORK_ORGANIZATIONS:
        if source_name in existing_names:
            continue
        db.add(SourceRegistry(
            source_name=source_name,
            official_url=url,
            collector_type="official_html",
            organization=organization,
            govt_level=govt_level,
            category=category,
            schedule="daily",
            status="disabled",
        ))
        created.append(source_name)
    db.commit()
    return {"created": created, "skipped_existing": sorted(existing_names & {n for n, *_ in FRAMEWORK_ORGANIZATIONS})}
