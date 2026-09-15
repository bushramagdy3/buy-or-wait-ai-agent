from calendar import monthrange
from datetime import timedelta

from event_utils import event_date_for, safe_amount


ALLOWED_DAY_GAPS = {5, 7, 10, 14, 21}
LATEST_AMOUNT_CATEGORIES = {"rent", "utilities", "insurance"}


def build_event_calendar(request_date, events):
    """Build a 90-day calendar using known events and simple recurrence rules."""
    end_date = request_date + timedelta(days=90)
    event_calendar = {}
    known_keys = set()

    # Start with every date so balance simulation can walk day by day later.
    current_date = request_date
    while current_date <= end_date:
        event_calendar[current_date.isoformat()] = []
        current_date += timedelta(days=1)

    # Add pending/scheduled events first because they are explicit facts.
    for event in events:
        event_date = event_date_for(event)
        if not event_date or event_date < request_date or event_date > end_date:
            continue
        if not should_add_known_event(event):
            continue

        calendar_event = make_calendar_event(event, event_date, "known")
        event_calendar[event_date.isoformat()].append(calendar_event)
        known_keys.add(event_key(calendar_event))

    # Then infer recurring events from settled history.
    for event in infer_recurring_events(events, request_date, end_date):
        if event_key(event) in known_keys:
            continue
        event_calendar[event["date"]].append(event)

    return event_calendar


def should_add_known_event(event):
    """Keep explicit future cash events, but avoid unsafe pending credits."""
    status = str(event.get("status", "")).strip()
    direction = str(event.get("direction", "")).strip()

    if direction == "non_cash":
        return False
    if status == "scheduled":
        return True
    if status == "pending" and direction == "debit":
        return True
    return False


def infer_recurring_events(events, request_date, end_date):
    """Find regular settled events and project them into the 90-day window."""
    groups = {}

    for event in events:
        if str(event.get("status", "")).strip() != "settled":
            continue
        if str(event.get("direction", "")).strip() == "non_cash":
            continue
        if str(event.get("event_type", "")).strip() not in [
            "expense",
            "debt_payment",
            "subscription",
            "income",
        ]:
            continue

        event_date = event_date_for(event)
        amount = safe_amount(event)
        if not event_date or event_date >= request_date or amount is None:
            continue

        groups.setdefault(recurrence_key(event, event_date), []).append(
            (event_date, event)
        )

    recurring_events = []
    for group_events in groups.values():
        group_events.sort(key=lambda item: item[0])
        if len(group_events) < 3:
            continue

        recurrence = detect_recurrence([date for date, _event in group_events])
        if recurrence is None:
            continue

        last_date, last_event = group_events[-1]
        if is_stale_pattern(last_date, request_date, recurrence):
            continue

        amount = recurring_amount([event for _date, event in group_events])
        for forecast_date in future_dates(last_date, recurrence, request_date, end_date):
            forecast_event = make_calendar_event(last_event, forecast_date, "recurring")
            forecast_event["amount"] = amount
            forecast_event["event_id"] = f"expected_{last_event.get('event_id', '')}"
            forecast_event["status"] = "expected"
            recurring_events.append(forecast_event)

    return recurring_events


def detect_recurrence(dates):
    """Return monthly or approved repeated day gaps."""
    gaps = [(dates[index] - dates[index - 1]).days for index in range(1, len(dates))]
    if not gaps:
        return None

    # Month lengths vary, so check calendar-month patterns before exact gaps.
    if is_monthly_shape(dates, gaps):
        return {"unit": "months"}

    # Only infer common short patterns; random repeated gaps are too noisy.
    best_days = None
    best_match_count = 0
    for gap in sorted(ALLOWED_DAY_GAPS):
        match_count = gaps.count(gap)
        match_ratio = match_count / len(gaps)
        if match_count >= 2 and match_ratio >= 0.7 and match_count > best_match_count:
            best_days = gap
            best_match_count = match_count

    if best_days is not None:
        return {"unit": "days", "days": best_days}

    return None


def future_dates(last_date, recurrence, request_date, end_date):
    """Generate future recurrence dates inside the forecast window."""
    next_date = add_interval(last_date, recurrence)
    while next_date < request_date:
        next_date = add_interval(next_date, recurrence)

    while next_date <= end_date:
        yield next_date
        next_date = add_interval(next_date, recurrence)


def add_interval(event_date, recurrence):
    if recurrence["unit"] == "days":
        return event_date + timedelta(days=recurrence["days"])
    return add_month(event_date)


def add_month(event_date):
    """Move one month ahead and clamp the day for short months."""
    month = event_date.month + 1
    year = event_date.year
    if month == 13:
        month = 1
        year += 1

    day = min(event_date.day, monthrange(year, month)[1])
    return event_date.replace(year=year, month=month, day=day)


def is_stale_pattern(last_date, request_date, recurrence):
    """Skip old patterns that probably stopped before the request date."""
    if recurrence["unit"] == "months":
        stale_days = 65
    else:
        stale_days = max(7, recurrence["days"] * 2)
    return last_date + timedelta(days=stale_days) < request_date


def is_monthly_shape(dates, gaps):
    """Detect same-day-of-month patterns without blocking other intervals."""
    monthish_gaps = [gap for gap in gaps if 27 <= gap <= 32]
    same_day_count = sum(1 for date in dates if date.day == dates[-1].day)
    return (
        len(monthish_gaps) >= 2
        and len(monthish_gaps) / len(gaps) >= 0.7
        and same_day_count / len(dates) >= 0.7
    )


def recurring_amount(events):
    """Choose latest for fixed streams, average for variable spending."""
    recent_amounts = [safe_amount(event) for event in events[-3:]]
    recent_amounts = [amount for amount in recent_amounts if amount is not None]

    if not recent_amounts:
        return 0

    last_event = events[-1]
    event_type = str(last_event.get("event_type", "")).strip()
    category = str(last_event.get("category", "")).strip()

    if (
        event_type in ["income", "subscription", "debt_payment"]
        or category in LATEST_AMOUNT_CATEGORIES
    ):
        return recent_amounts[-1]

    return sum(recent_amounts) / len(recent_amounts)


def make_calendar_event(event, event_date, source):
    event_id = str(event.get("event_id", "")).strip()
    return {
        "event_id": event_id,
        "original_event_id": event_id,
        "date": event_date.isoformat(),
        "event_type": str(event.get("event_type", "")).strip(),
        "description": str(event.get("description", "")).strip(),
        "category": str(event.get("category", "")).strip(),
        "direction": str(event.get("direction", "")).strip(),
        "amount": safe_amount(event),
        "currency": str(event.get("currency", "")).strip(),
        "status": str(event.get("status", "")).strip(),
        "flexibility": str(event.get("flexibility", "")).strip(),
        "minimum_allowed_amount": str(
            event.get("minimum_allowed_amount", "")
        ).strip(),
        "source": source,
    }


def recurrence_key(event, event_date=None):
    """Group expenses broadly; split income streams by day of month."""
    key = (
        str(event.get("event_type", "")).strip(),
        str(event.get("category", "")).strip(),
        str(event.get("direction", "")).strip(),
        str(event.get("currency", "")).strip(),
    )

    if str(event.get("event_type", "")).strip() == "income" and event_date:
        key += (event_date.day,)

    return key


def event_key(event):
    """Prevent duplicate known and inferred events on the same date."""
    return (
        event["date"],
        event["event_type"],
        event["category"],
        event["direction"],
        event["currency"],
    )
