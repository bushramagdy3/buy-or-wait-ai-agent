from itertools import combinations

from event_utils import to_float


MAX_CHANGES = 3


def generate_change_sets(
    event_calendar,
    expenses_willing_to_reduce,
    expenses_willing_to_stop,
    protected_categories=None,
):
    """Return all allowed spending-change sets, up to three changes each."""
    changes = generate_allowed_changes(
        event_calendar,
        expenses_willing_to_reduce,
        expenses_willing_to_stop,
        protected_categories or [],
    )
    change_sets = []

    for size in range(1, min(MAX_CHANGES, len(changes)) + 1):
        for change_set in combinations(changes, size):
            if has_duplicate_event(change_set):
                continue
            change_sets.append(list(change_set))

    return change_sets


def generate_allowed_changes(
    event_calendar,
    expenses_willing_to_reduce,
    expenses_willing_to_stop,
    protected_categories,
):
    """Create single stop/reduce actions allowed by user and event flexibility."""
    reduce_categories = set(expenses_willing_to_reduce)
    stop_categories = set(expenses_willing_to_stop)
    protected = set(protected_categories)
    changes = []
    seen = set()

    for date in sorted(event_calendar):
        for event in event_calendar[date]:
            if not is_changeable_expense(event, protected):
                continue

            event_id = change_event_id(event)
            category = str(event.get("category", "")).strip()
            flexibility = str(event.get("flexibility", "")).strip()

            try:
                if category in reduce_categories and flexibility in [
                    "reducible",
                    "reducible_or_stoppable",
                ]:
                    add_reduce_change(changes, seen, event, event_id)

                if category in stop_categories and flexibility in [
                    "stoppable",
                    "reducible_or_stoppable",
                ]:
                    add_stop_change(changes, seen, event_id)
            except (TypeError, ValueError) as error:
                print(f"Skipping spending change due to error: {error}")

    return changes


def is_changeable_expense(event, protected_categories):
    """Only flexible recurring debit expenses in non-protected categories change."""
    category = str(event.get("category", "")).strip()
    event_type = str(event.get("event_type", "")).strip()

    if category in protected_categories:
        return False
    if str(event.get("source", "")).strip() != "recurring":
        return False
    if str(event.get("direction", "")).strip() != "debit":
        return False
    return event_type in ["expense", "subscription"]


def add_reduce_change(changes, seen, event, event_id):
    if not event_id or ("reduce_to", event_id) in seen:
        return

    minimum_allowed = str(event.get("minimum_allowed_amount", "")).strip()
    if not minimum_allowed:
        return

    current_amount = to_float(event.get("amount", "0"))
    new_value = to_float(minimum_allowed)
    if new_value >= current_amount:
        return

    seen.add(("reduce_to", event_id))
    changes.append(
        {
            "action": "reduce_to",
            "new_value": new_value,
            "event_id": event_id,
        }
    )


def add_stop_change(changes, seen, event_id):
    if not event_id or ("stop", event_id) in seen:
        return

    seen.add(("stop", event_id))
    changes.append(
        {
            "action": "stop",
            "new_value": None,
            "event_id": event_id,
        }
    )


def has_duplicate_event(change_set):
    """The same event cannot be reduced and stopped in one change set."""
    event_ids = [change["event_id"] for change in change_set]
    return len(event_ids) != len(set(event_ids))


def change_event_id(event):
    return str(event.get("original_event_id") or event.get("event_id", "")).strip()
