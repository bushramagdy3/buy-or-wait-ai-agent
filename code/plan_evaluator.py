from code.balance_simulation import simulate_calendar
from code.event_utils import parse_date, to_float


def find_safe_payment_plans(
    legal_plans, current_balance, minimum_balance, event_calendar
):
    """Return plans whose payments never push balance below the minimum."""
    safe_plans = []

    for plan in legal_plans:
        try:
            projection = simulate_plan(
                plan, current_balance, minimum_balance, event_calendar
            )
        except (TypeError, ValueError, KeyError) as error:
            print(f"Skipping payment plan due to error: {error}")
            continue

        if projection["is_safe"]:
            safe_plan = dict(plan)
            safe_plan["spending_changes"] = []
            safe_plan["balance_projection"] = projection
            safe_plans.append(safe_plan)

    return safe_plans


def find_safe_payment_plans_with_change_sets(
    legal_plans, change_sets, current_balance, minimum_balance, event_calendar
):
    """Try every change set with every legal plan and keep safe results."""
    safe_plans = []

    for change_set in change_sets:
        for plan in legal_plans:
            try:
                projection = simulate_plan(
                    plan,
                    current_balance,
                    minimum_balance,
                    event_calendar,
                    change_set,
                )
            except (TypeError, ValueError, KeyError) as error:
                print(f"Skipping changed payment plan due to error: {error}")
                continue

            if projection["is_safe"]:
                safe_plan = dict(plan)
                safe_plan["spending_changes"] = change_set
                safe_plan["balance_projection"] = projection
                safe_plans.append(safe_plan)

    return safe_plans


def simulate_plan(
    plan, current_balance, minimum_balance, event_calendar, change_set=None
):
    """Add plan payments to the calendar, then reuse the balance simulator."""
    calendar = apply_change_set(event_calendar, change_set or [])

    for payment in plan.get("payments", []):
        payment_date = parse_date(payment.get("date", "")).isoformat()
        payment_event = {
            "event_id": f"plan:{plan.get('option_id', '')}",
            "date": payment_date,
            "event_type": "request_payment",
            "description": str(plan.get("plan_name", "")),
            "direction": "debit",
            "amount": to_float(payment.get("amount", "0")),
            "status": "scheduled",
            "source": "payment_plan",
        }

        # Payment first on that date is the safer interpretation.
        calendar.setdefault(payment_date, []).insert(0, payment_event)

    return simulate_calendar(current_balance, minimum_balance, calendar)


def apply_change_set(event_calendar, change_set):
    """Apply stop/reduce changes to matching projected recurring events."""
    changes_by_event_id = {
        str(change.get("event_id", "")).strip(): change for change in change_set
    }
    calendar = {}

    for date, events in event_calendar.items():
        calendar[date] = []
        for event in events:
            event_copy = dict(event)
            event_id = str(
                event_copy.get("original_event_id") or event_copy.get("event_id", "")
            ).strip()
            change = changes_by_event_id.get(event_id)

            if not change:
                calendar[date].append(event_copy)
                continue

            if change.get("action") == "stop":
                continue
            if change.get("action") == "reduce_to":
                event_copy["amount"] = to_float(change.get("new_value", "0"))

            calendar[date].append(event_copy)

    return calendar


def choose_highest_ranking_plan(safe_plans, request):
    """Pick the safest allowed plan using the problem statement tie-breakers."""
    if not safe_plans:
        return None
    return sorted(safe_plans, key=lambda plan: plan_rank(plan, request))[0]


def plan_rank(plan, request):
    completion_date = plan_completion_date(plan)
    deadline = safe_date(request.get("desired_completion_date", ""))
    completes_by_deadline = deadline is None or (
        completion_date is not None and completion_date <= deadline
    )

    return (
        0 if completes_by_deadline else 1,
        0 if has_no_spending_changes(plan) else 1,
        total_paid(plan),
        plan_start_date(plan).isoformat(),
        len(plan.get("payments", [])),
        option_id_rank(plan.get("option_id", "")),
    )


def plan_start_date(plan):
    dates = [parse_date(payment.get("date", "")) for payment in plan.get("payments", [])]
    return min(dates)


def plan_completion_date(plan):
    dates = [parse_date(payment.get("date", "")) for payment in plan.get("payments", [])]
    return max(dates) if dates else None


def total_paid(plan):
    return sum(to_float(payment.get("amount", "0")) for payment in plan.get("payments", []))


def has_no_spending_changes(plan):
    changes = plan.get("spending_changes", [])
    return not changes or changes == "none"


def option_id_rank(option_id):
    digits = "".join(char for char in str(option_id) if char.isdigit())
    if not digits:
        return (999999, str(option_id))
    return (int(digits), str(option_id))


def safe_date(value):
    try:
        return parse_date(value)
    except ValueError:
        return None
