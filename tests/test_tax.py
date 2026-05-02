from datetime import datetime

from app.services.tax_service import TunisianTaxService


def test_due_date_rolls_over_year_for_december():
    svc = TunisianTaxService()
    # Period ending in December 2024 should have due date Jan 28, 2025
    period_start = datetime(2024, 12, 1)
    period_end = datetime(2024, 12, 31)

    breakdown = svc.calculate_period_taxes("biz1", [], [], period_start, period_end)
    assert breakdown.due_date.year == 2025
    assert breakdown.due_date.month == 1
    assert breakdown.due_date.day == 28
