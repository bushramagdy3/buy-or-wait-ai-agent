from event_utils import to_float


MONEY_EPSILON = 0.005


def simulate_calendar(current_balance, required_minimum_balance, event_calendar):
    """Apply calendar events in date order and track projected balances."""
    balance = round_money(current_balance)
    required_minimum_balance = round_money(required_minimum_balance)
    lowest_balance = balance
    lowest_balance_date = ""
    balance_by_date = {}

    for date in sorted(event_calendar):
        if not lowest_balance_date:
            lowest_balance_date = date

        for event in event_calendar[date]:
            amount = round_money(event.get("amount", "0"))
            direction = str(event.get("direction", "")).strip()

            # Debits reduce cash, credits increase cash, non-cash events are ignored.
            if direction == "debit":
                balance -= amount
            elif direction == "credit":
                balance += amount
            balance = round_money(balance)

        # Judge safety after all same-day credits and debits have landed.
        if balance < lowest_balance:
            lowest_balance = balance
            lowest_balance_date = date

        balance_by_date[date] = balance

    return {
        "is_safe": lowest_balance + MONEY_EPSILON >= required_minimum_balance,
        "lowest_balance": lowest_balance,
        "lowest_balance_date": lowest_balance_date,
        "ending_balance": balance,
        "balance_by_date": balance_by_date,
    }


def find_earliest_safe_payment_date(amount_to_pay, required_minimum_balance, balance_by_date):
    """Return the first date where paying keeps every later balance safe."""
    amount_to_pay = round_money(amount_to_pay)
    required_minimum_balance = round_money(required_minimum_balance)

    for pay_date in sorted(balance_by_date):
        is_safe = True

        for date in sorted(balance_by_date):
            if date < pay_date:
                continue

            # Paying on pay_date lowers that day and every later projected balance.
            projected_balance = round_money(balance_by_date[date] - amount_to_pay)
            if projected_balance + MONEY_EPSILON < required_minimum_balance:
                is_safe = False
                break

        if is_safe:
            return pay_date

    return ""


def round_money(value):
    """Round money to cents before comparing balances."""
    return round(to_float(value), 2)
