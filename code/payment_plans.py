from datetime import timedelta

from code.event_utils import parse_date, to_float


def build_legal_payment_plans(
    request,
    payment_options,
    accepted_methods,
    max_installment_months,
    amount_safe_to_pay,
    earliest_date_for_full_payment,
):
    """Build every allowed full, wait, partial, and installment plan."""
    legal_plans = []
    legal_methods = get_legal_methods(request, payment_options, accepted_methods)
    full_option = find_option(payment_options, "full_payment")

    # Full payment uses the seller full-payment option, paid on the request date.
    if "full_payment" in legal_methods:
        append_plan(legal_plans, build_full_payment_plan, request, full_option)

    # Waiting still means a future full payment, so the user must accept full payment.
    if "wait" in legal_methods:
        append_plan(
            legal_plans,
            build_wait_plan,
            request,
            full_option,
            earliest_date_for_full_payment,
        )

    # Partial payment is allowed by the request text, not usually by seller option rows.
    if "partial_payment" in legal_methods:
        append_plan(
            legal_plans,
            build_partial_payment_plan,
            request,
            find_option(payment_options, "partial_payment"),
            amount_safe_to_pay,
            earliest_date_for_full_payment,
        )

    for option in payment_options:
        if str(option.get("payment_method", "")).strip() != "installments":
            continue
        if "installments" not in legal_methods:
            continue
        if not installment_is_allowed(option, max_installment_months):
            continue
        append_plan(legal_plans, build_installment_plan, request, option)

    return legal_plans


def get_legal_methods(request, payment_options, accepted_methods):
    """Merge user preferences with methods the request can actually use."""
    accepted = set(accepted_methods)
    allowed = {
        str(option.get("payment_method", "")).strip()
        for option in payment_options
        if str(option.get("payment_method", "")).strip()
    }

    # Partial is controlled by the request flag, not by seller option rows.
    if truthy(request.get("allows_partial_payment")):
        allowed.add("partial_payment")

    # Wait is a timing choice for a full payment, not a profile preference value.
    if "full_payment" in accepted:
        accepted.add("wait")
    if "full_payment" in allowed:
        allowed.add("wait")

    return accepted & allowed


def build_full_payment_plan(request, option):
    request_date = safe_date(request.get("request_date"))
    if request_date is None:
        return None

    return {
        "plan_name": "full_payment",
        "option_id": option_id(option, "derived_full_payment"),
        "payments": [
            {
                "date": request_date.isoformat(),
                "amount": to_float(request.get("requested_amount", "0")),
            }
        ],
    }


def build_wait_plan(request, option, earliest_date_for_full_payment):
    request_date = safe_date(request.get("request_date"))
    pay_date = safe_date(earliest_date_for_full_payment)
    deadline = safe_date(request.get("desired_completion_date"))
    if request_date is None or pay_date is None:
        return None
    if pay_date <= request_date:
        return None
    if deadline and pay_date > deadline:
        return None

    return {
        "plan_name": "wait",
        "option_id": option_id(option, "derived_wait"),
        "payments": [
            {
                "date": pay_date.isoformat(),
                "amount": to_float(request.get("requested_amount", "0")),
            }
        ],
    }


def build_partial_payment_plan(
    request, option, amount_safe_to_pay, earliest_date_for_full_payment
):
    request_date = safe_date(request.get("request_date"))
    second_date = safe_date(earliest_date_for_full_payment)
    deadline = safe_date(request.get("desired_completion_date"))
    requested_amount = to_float(request.get("requested_amount", "0"))
    first_amount = round(min(to_float(amount_safe_to_pay), requested_amount), 2)
    second_amount = round(requested_amount - first_amount, 2)

    if request_date is None or second_date is None:
        return None
    if deadline and second_date > deadline:
        return None
    if first_amount <= 0 or second_amount <= 0:
        return None

    return {
        "plan_name": "partial_payment",
        "option_id": option_id(option, "derived_partial_payment"),
        "payments": [
            {"date": request_date.isoformat(), "amount": first_amount},
            {"date": second_date.isoformat(), "amount": second_amount},
        ],
    }


def build_installment_plan(request, option):
    first_payment_date = safe_date(option.get("first_payment_date"))
    deadline = safe_date(request.get("desired_completion_date"))
    if first_payment_date is None:
        return None

    amount = to_float(option.get("payment_amount", "0"))
    number_of_payments = int(to_float(option.get("number_of_payments", "1")))
    frequency_days = int(to_float(option.get("payment_frequency_days", "0")))
    if number_of_payments <= 0:
        return None

    payments = []

    for index in range(number_of_payments):
        payment_date = first_payment_date + timedelta(days=frequency_days * index)
        payments.append({"date": payment_date.isoformat(), "amount": amount})

    if deadline and safe_date(payments[-1]["date"]) > deadline:
        return None

    return {
        "plan_name": "installments",
        "option_id": option_id(option, "derived_installments"),
        "payments": payments,
    }


def installment_is_allowed(option, max_installment_months):
    """Reject installment options longer than the user's stated limit."""
    if max_installment_months is None:
        return False

    try:
        number_of_payments = int(to_float(option.get("number_of_payments", "0")))
        return number_of_payments <= max_installment_months
    except (TypeError, ValueError):
        return False


def append_plan(plans, builder, *args):
    """Skip malformed plans without stopping the request."""
    try:
        plan = builder(*args)
    except (TypeError, ValueError, IndexError) as error:
        print(f"Skipping payment option due to error: {error}")
        return

    if not plan or not plan.get("payments"):
        return
    plans.append(plan)


def find_option(payment_options, method):
    for option in payment_options:
        if str(option.get("payment_method", "")).strip() == method:
            return option
    return None


def option_id(option, fallback):
    if not option:
        return fallback
    return str(option.get("payment_option_id", "") or fallback).strip()


def safe_date(value):
    try:
        return parse_date(value)
    except ValueError:
        return None


def truthy(value):
    return str(value or "").strip().lower() in ["true", "yes", "1"]
