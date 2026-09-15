from code.balance_simulation import (
    find_earliest_safe_payment_date,
    round_money,
    simulate_calendar,
)
from code.currency_utils import convert_events_to_home_currency
from code.decision_explanation import generate_decision_explanation
from code.event_calendar import build_event_calendar
from code.event_image_repair import fill_missing_event_fields
from code.event_message_updates import apply_message_event_updates
from code.event_utils import find_image_path, parse_date, split_list, to_float
from code.payment_plans import build_legal_payment_plans
from code.plan_evaluator import (
    choose_highest_ranking_plan,
    find_safe_payment_plans,
    find_safe_payment_plans_with_change_sets,
)
from code.spending_changes import generate_change_sets


def resolve_request(request, data):
    """Prepare all request context before the final decision logic."""
    request_id = str(request.get("request_id", "")).strip()
    user_info = collect_user_information(request, data)
    profile = user_info["profile"]

    current_balance = to_float(profile.get("current_available_balance", "0"))
    minimum_balance = to_float(profile.get("minimum_balance_to_keep", "0"))
    accepted_payment_methods = split_list(
        profile.get("payment_methods_user_will_consider", "")
    )
    max_installment_months = parse_optional_int(
        profile.get("max_installment_months", "")
    )
    protected_categories = split_list(profile.get("expense_categories_to_protect", ""))
    expenses_willing_to_reduce = split_list(
        profile.get("expense_categories_user_is_willing_to_reduce", "")
    )
    expenses_willing_to_cancel = split_list(
        profile.get("expense_categories_user_is_willing_to_stop", "")
    )
    expenses_willing_to_reduce_or_cancel = sorted(
        set(expenses_willing_to_reduce + expenses_willing_to_cancel)
    )

    request_date = parse_date(request.get("request_date", ""))

    # Images fill missing fields first, then messages override because they are truth.
    print(f"  {request_id}: repairing image evidence.")
    financial_events = fill_missing_event_fields(
        user_info["financial_events"], user_info["images"]
    )
    print(f"  {request_id}: applying message evidence.")
    financial_events = apply_message_event_updates(
        financial_events, user_info["messages"]
    )
    print(f"  {request_id}: converting currencies and building calendar.")
    financial_events = convert_events_to_home_currency(
        financial_events,
        profile.get("home_currency", ""),
        data.get("exchange_rates", []),
    )
    event_calendar = build_event_calendar(request_date, financial_events)
    print(f"  {request_id}: simulating payment plans.")
    allowed_change_sets = generate_change_sets(
        event_calendar,
        expenses_willing_to_reduce,
        expenses_willing_to_cancel,
        protected_categories,
    )
    balance_projection = simulate_calendar(
        current_balance, minimum_balance, event_calendar
    )
    amount_safe_to_pay = round_money(
        max(0, balance_projection["lowest_balance"] - minimum_balance)
    )
    earliest_date_for_full_payment = find_earliest_safe_payment_date(
        request.get("requested_amount", "0"),
        minimum_balance,
        balance_projection["balance_by_date"],
    )
    legal_payment_plans = build_legal_payment_plans(
        request,
        user_info["payment_options"],
        accepted_payment_methods,
        max_installment_months,
        amount_safe_to_pay,
        earliest_date_for_full_payment,
    )
    safe_payment_plans = find_safe_payment_plans(
        legal_payment_plans,
        current_balance,
        minimum_balance,
        event_calendar,
    )
    if not safe_payment_plans:
        safe_payment_plans = find_safe_payment_plans_with_change_sets(
            legal_payment_plans,
            allowed_change_sets,
            current_balance,
            minimum_balance,
            event_calendar,
        )

    selected_payment_plan = None
    selected_change_set = []
    if safe_payment_plans:
        selected_payment_plan = choose_highest_ranking_plan(
            safe_payment_plans, request
        )
        selected_change_set = selected_payment_plan.get("spending_changes", [])

    print(f"  {request_id}: generating explanation.")
    decision_explanation = generate_decision_explanation(
        request,
        profile,
        selected_payment_plan,
        selected_change_set,
        amount_safe_to_pay,
        earliest_date_for_full_payment,
        balance_projection,
    )
    if selected_payment_plan:
        selected_payment_plan["decision_explanation"] = decision_explanation

    return build_output_row(
        request,
        selected_payment_plan,
        selected_change_set,
        amount_safe_to_pay,
        earliest_date_for_full_payment,
        decision_explanation,
    )


def collect_user_information(request, data):
    """Collect profile, events, messages, image paths, and payment options."""
    user_id = str(request.get("user_id", "")).strip()
    request_id = str(request.get("request_id", "")).strip()

    if not user_id:
        raise ValueError("request is missing user_id")
    if not request_id:
        raise ValueError("request is missing request_id")

    profile = None
    for row in data.get("financial_profiles", []):
        if str(row.get("user_id", "")).strip() == user_id:
            profile = row
            break

    if profile is None:
        raise ValueError(f"profile not found for {user_id}")

    financial_events = [
        row
        for row in data.get("financial_events", [])
        if str(row.get("user_id", "")).strip() == user_id
    ]

    messages = [
        row
        for row in data.get("messages", [])
        if str(row.get("user_id", "")).strip() == user_id
    ]

    images = []
    for row in data.get("images", []):
        if str(row.get("user_id", "")).strip() != user_id:
            continue

        image_row = dict(row)
        image_row["image_path"] = find_image_path(row.get("image_id", ""))
        images.append(image_row)

    payment_options = [
        row
        for row in data.get("request_payment_options", [])
        if str(row.get("request_id", "")).strip() == request_id
    ]

    return {
        "request": request,
        "user_id": user_id,
        "request_id": request_id,
        "profile": profile,
        "financial_events": financial_events,
        "messages": messages,
        "images": images,
        "payment_options": payment_options,
    }


def parse_optional_int(value):
    value = str(value or "").strip()
    if not value:
        return None
    return int(to_float(value))


def build_output_row(
    request,
    selected_plan,
    selected_change_set,
    amount_safe_to_pay,
    earliest_date_for_full_payment,
    decision_explanation,
):
    requested_amount = to_float(request.get("requested_amount", "0"))
    safe_amount = max(0, min(to_float(amount_safe_to_pay), requested_amount))

    return {
        "request_id": str(request.get("request_id", "")).strip(),
        "amount_safe_to_pay": format_amount(safe_amount),
        "affordability_status": affordability_status(
            selected_plan, selected_change_set
        ),
        "recommended_payment_method": recommended_method(selected_plan),
        "payment_plan": format_payment_plan(selected_plan),
        "earliest_date_for_full_payment": str(
            earliest_date_for_full_payment or ""
        ).strip(),
        "spending_changes_needed": format_spending_changes(selected_change_set),
        "decision_explanation": str(decision_explanation or "").strip(),
    }


def affordability_status(selected_plan, selected_change_set):
    if not selected_plan:
        return "not_affordable"
    if selected_change_set:
        return "affordable_with_plan"

    method = str(selected_plan.get("plan_name", "")).strip()
    if method == "full_payment":
        return "affordable_now"
    if method == "wait":
        return "affordable_later"
    return "affordable_with_plan"


def recommended_method(selected_plan):
    if not selected_plan:
        return "not_recommended"
    return str(selected_plan.get("plan_name", "")).strip()


def format_payment_plan(selected_plan):
    if not selected_plan:
        return "none"

    payments = selected_plan.get("payments", [])
    if not payments:
        return "none"

    parts = []
    for payment in sorted(payments, key=lambda item: item.get("date", "")):
        date = str(payment.get("date", "")).strip()
        amount = format_amount(payment.get("amount", "0"))
        if date:
            parts.append(f"{date}:{amount}")

    return "|".join(parts) if parts else "none"


def format_spending_changes(change_set):
    if not change_set:
        return "none"

    parts = []
    for change in change_set[:3]:
        event_id = str(change.get("event_id", "")).strip()
        action = str(change.get("action", "")).strip()
        if not event_id:
            continue
        if action == "stop":
            parts.append(f"stop:{event_id}")
        elif action == "reduce_to":
            parts.append(
                f"reduce_to:{event_id}:{format_amount(change.get('new_value', '0'))}"
            )

    return "|".join(parts) if parts else "none"


def format_amount(value):
    amount = round(to_float(value), 2)
    if amount == 0:
        amount = 0
    return f"{amount:.2f}".rstrip("0").rstrip(".")
