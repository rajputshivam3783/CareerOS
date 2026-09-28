"""Unit tests for the V5 eligibility engine.

Uses plain SimpleNamespace stand-ins for Job/Profile since
eligibility() only reads a handful of attributes — no DB needed here.
"""

from datetime import date
from types import SimpleNamespace

from app.services.eligibility import compute_age, eligibility, parse_age_range


def make_job(**overrides):
    defaults = dict(
        qualification="Bachelor's degree in any discipline",
        age_limit="18-27 years",
        deadline=None,
        exam_date=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_profile(**overrides):
    defaults = dict(
        highest_qualification="Graduate",
        date_of_birth=date(2000, 1, 1),
        reservation_category="General",
        is_pwd=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_parse_age_range_handles_common_formats():
    assert parse_age_range("18-27 years") == (18, 27)
    assert parse_age_range("Between 21 and 30 years") == (21, 30)
    assert parse_age_range("Not exceeding 30 years") == (None, 30)
    assert parse_age_range("Minimum 18 years") == (18, None)
    assert parse_age_range("See official notification") == (None, None)
    assert parse_age_range(None) == (None, None)


def test_compute_age_before_and_after_birthday():
    dob = date(2000, 6, 15)
    assert compute_age(dob, date(2025, 6, 14)) == 24  # birthday not yet reached this year
    assert compute_age(dob, date(2025, 6, 15)) == 25  # birthday reached today


def test_eligibility_with_no_profile_is_unclear():
    result = eligibility(make_job(), None)
    assert result["eligible"] is None
    assert result["confidence"] == 0


def test_eligibility_within_age_and_qualification_is_eligible():
    job = make_job(qualification="Graduate in any discipline", age_limit="18-30 years")
    profile = make_profile(date_of_birth=date(2000, 1, 1))  # ~25 years old
    result = eligibility(job, profile)
    assert result["eligible"] is True
    assert result["qualification_check"] is True
    assert result["age_check"] is True


def test_eligibility_over_age_limit_is_ineligible():
    job = make_job(qualification="Graduate in any discipline", age_limit="18-27 years")
    profile = make_profile(date_of_birth=date(1990, 1, 1))  # well past 27
    result = eligibility(job, profile)
    assert result["eligible"] is False
    assert result["age_check"] is False


def test_eligibility_category_relaxation_can_extend_eligible_age():
    # ~30 years old: outside 18-27 unrelaxed, but SC/ST get +5 years (max becomes 32).
    job = make_job(qualification="Graduate in any discipline", age_limit="18-27 years")
    over_limit_general = make_profile(date_of_birth=date(1996, 1, 1), reservation_category="General")
    with_relaxation = make_profile(date_of_birth=date(1996, 1, 1), reservation_category="SC")

    general_result = eligibility(job, over_limit_general)
    relaxed_result = eligibility(job, with_relaxation)

    assert general_result["age_check"] is False
    assert relaxed_result["age_check"] is True
    assert relaxed_result["age_details"]["relaxation_years_applied"] == 5


def test_eligibility_unverifiable_fields_return_none_not_false():
    job = make_job(qualification="See official notification", age_limit="See official notification")
    profile = make_profile()
    result = eligibility(job, profile)
    assert result["eligible"] is None
    assert result["qualification_check"] is None
    assert result["age_check"] is None
