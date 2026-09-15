from event_utils import event_date_for, to_float


def convert_events_to_home_currency(events, home_currency, exchange_rates):
    """Convert cash events into the user's home currency before simulation."""
    home_currency = str(home_currency or "").strip()
    rates = build_rate_lookup(exchange_rates)
    converted_events = []

    for event in events:
        converted_event = dict(event)
        currency = str(event.get("currency", "")).strip()
        direction = str(event.get("direction", "")).strip()

        if not home_currency or not currency or currency == home_currency:
            converted_events.append(converted_event)
            continue

        # Non-cash values are never available cash, so do not convert them here.
        if direction == "non_cash":
            converted_events.append(converted_event)
            continue

        try:
            event_date = event_date_for(event)
            if not event_date:
                raise ValueError("missing event date")

            rate = rates[(event_date.isoformat(), currency, home_currency)]
            converted_event["amount"] = format_number(
                to_float(event.get("amount", "0")) * rate
            )

            if str(event.get("minimum_allowed_amount", "")).strip():
                converted_event["minimum_allowed_amount"] = format_number(
                    to_float(event.get("minimum_allowed_amount", "0")) * rate
                )

            converted_event["currency"] = home_currency
        except Exception as error:
            print(
                "Could not convert event "
                f"{event.get('event_id', '')} from {currency} to "
                f"{home_currency}: {error}"
            )

        converted_events.append(converted_event)

    return converted_events


def build_rate_lookup(exchange_rates):
    """Index exchange rates by exact date and currency direction."""
    rates = {}
    for row in exchange_rates:
        key = (
            str(row.get("rate_date", "")).strip(),
            str(row.get("from_currency", "")).strip(),
            str(row.get("to_currency", "")).strip(),
        )
        try:
            rates[key] = to_float(row.get("rate", ""))
        except ValueError:
            continue
    return rates


def format_number(value):
    """Keep converted CSV-style numbers compact but precise enough for money."""
    amount = round(to_float(value), 2)
    return f"{amount:.2f}".rstrip("0").rstrip(".")
