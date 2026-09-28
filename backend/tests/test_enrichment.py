"""V25.7 — auto-enrichment extraction (pure functions, no network/DB)."""
from datetime import date

from app.ingestion.services.enrichment import extract_fields, find_dates

SAMPLE = """
Staff Selection Commission
Advertisement No. 04/2026
Notice of Combined Graduate Level Examination
Total Vacancies : 14,582 posts
Online application starts on 10.10.2026
Last date for online application: 30/10/2026
Date of Computer Based Examination: 15 December 2026
Educational Qualification: Bachelor's Degree from a recognised University
Age Limit: 18-27 years as on 01-08-2026
Age Relaxation: SC/ST 5 years, OBC 3 years
Application Fee: Rs. 100/- (Women/SC/ST/PwBD exempted)
Pay Level-6 Rs. 35,400 - 1,12,400
Selection Process: Tier-I CBT, Tier-II CBT, Document Verification
"""


def test_dates_all_formats():
    assert find_dates("on 10.10.2026 and 5th Nov, 2026 and December 3, 2026") == [
        date(2026, 10, 10), date(2026, 11, 5), date(2026, 12, 3)]
    assert find_dates("31/02/2026") == []  # impossible date ignored


def test_full_extraction():
    f = extract_fields(SAMPLE)
    assert f["vacancies"] == 14582
    assert f["start_date"] == date(2026, 10, 10)
    assert f["deadline"] == date(2026, 10, 30)
    assert f["exam_date"] == date(2026, 12, 15)
    assert f["ad_number"] == "04/2026"
    assert "Bachelor" in f["qualification"]
    assert f["age_limit"].startswith("18-27")
    assert "SC/ST 5 years" in f["age_relaxation"]
    assert "Rs. 100" in f["application_fee"]
    assert f["pay_level"] == "Level 6"
    assert "35,400" in f["salary"]
    assert "Tier-I" in f["selection_process"]


def test_missing_fields_are_omitted_not_invented():
    assert extract_fields("Welcome to our website. Contact us.") == {}
