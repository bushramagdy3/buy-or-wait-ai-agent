import json
import os

from llm_utils import invoke_with_rate_limit_retry
from settings import OPENAI_API_KEY


def generate_decision_explanation(
    request,
    profile,
    selected_plan,
    selected_change_set,
    amount_safe_to_pay,
    earliest_date_for_full_payment,
    balance_projection,
):
    """Use an LLM for a concise explanation, with a safe fallback."""
    try:
        return get_llm_explanation(
            request,
            profile,
            selected_plan,
            selected_change_set,
            amount_safe_to_pay,
            earliest_date_for_full_payment,
            balance_projection,
        )
    except Exception as error:
        print(f"Could not generate LLM explanation: {error}")
        return fallback_explanation(
            request,
            profile,
            selected_plan,
            selected_change_set,
            amount_safe_to_pay,
            earliest_date_for_full_payment,
        )


def get_llm_explanation(
    request,
    profile,
    selected_plan,
    selected_change_set,
    amount_safe_to_pay,
    earliest_date_for_full_payment,
    balance_projection,
):
    """Ask the LLM to explain only the selected calculated plan."""
    from langchain_openai import ChatOpenAI
    from pydantic import BaseModel, Field

    class ExplanationModel(BaseModel):
        decision_explanation: str = Field(
            description="One concise grounded explanation for the selected plan"
        )

    model_name = os.getenv("EXPLANATION_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(
        model=model_name,
        temperature=0,
        openai_api_key=OPENAI_API_KEY,
    ).with_structured_output(ExplanationModel, include_raw=True)

    context = {
        "request": request,
        "home_currency": profile.get("home_currency", ""),
        "minimum_balance_to_keep": profile.get("minimum_balance_to_keep", ""),
        "amount_safe_to_pay_today": amount_safe_to_pay,
        "earliest_date_for_full_payment": earliest_date_for_full_payment,
        "selected_plan": compact_plan(selected_plan),
        "selected_spending_changes": selected_change_set,
        "lowest_projected_balance": balance_projection.get("lowest_balance", ""),
        "lowest_projected_balance_date": balance_projection.get(
            "lowest_balance_date", ""
        ),
    }

    prompt = (
        "Write only the decision_explanation cell for output.csv.\n"
        "You must explain the already-selected structured decision. Do not "
        "change, question, contradict, or improve the selected plan.\n\n"
        "Hard rules:\n"
        "- Use only facts from Context.\n"
        "- Do not mention a payment method, date, amount, or spending change "
        "unless it appears in Context.\n"
        "- Do not say a plan is unsafe if selected_plan is not null.\n"
        "- Do not say the user can pay today unless the selected plan's first "
        "payment date equals request.request_date.\n"
        "- Do not cite the lowest projected balance unless it is needed; prefer "
        "saying the minimum balance is protected.\n"
        "- Keep the answer to one or two short sentences.\n"
        "- Use the home currency code before money amounts.\n\n"
        "Preferred wording by selected_plan.plan_name:\n"
        "full_payment: 'Pay {currency} {amount} today. This leaves at least "
        "{currency} {minimum_balance} available over the next 90 days.'\n"
        "wait: 'Pay {currency} {amount} in full on {payment_date}. Paying "
        "earlier would take the balance below the {currency} "
        "{minimum_balance} minimum.'\n"
        "partial_payment: 'Pay {currency} {first_amount} today and the "
        "remaining {currency} {second_amount} on {second_date}. This completes "
        "the full request and keeps the {currency} {minimum_balance} minimum "
        "protected.'\n"
        "installments: 'Use {number_of_payments} installments of {currency} "
        "{payment_amount}, starting {first_payment_date}. This leaves at "
        "least {currency} {minimum_balance} available.'\n"
        "not_recommended/no selected_plan: 'Do not make this payment by "
        "{desired_completion_date}. None of the available options keeps the "
        "{currency} {minimum_balance} minimum protected.'\n\n"
        "If selected_spending_changes is not empty, begin with the required "
        "changes, such as 'Stop ...' or 'Reduce ...', then explain the payment. "
        "Never invent category names for changes; use the action and event_id "
        "from Context if no plain description is supplied.\n\n"
        f"Context:\n{json.dumps(context, default=str)}"
    )

    result = invoke_with_rate_limit_retry(
        llm,
        [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        usage_step="decision_explanation",
        model_name=model_name,
    )

    if isinstance(result, dict):
        if result.get("parsing_error"):
            raise ValueError(result["parsing_error"])
        result = result.get("parsed")
    if result is None:
        raise ValueError("LLM did not return a parsed explanation")

    if hasattr(result, "model_dump"):
        explanation = result.model_dump()["decision_explanation"]
    else:
        explanation = result.dict()["decision_explanation"]

    return validate_explanation(explanation)


def compact_plan(selected_plan):
    """Keep the LLM prompt focused on explanation-relevant facts."""
    if not selected_plan:
        return None

    projection = selected_plan.get("balance_projection", {})
    return {
        "plan_name": selected_plan.get("plan_name", ""),
        "option_id": selected_plan.get("option_id", ""),
        "payments": selected_plan.get("payments", []),
        "spending_changes": selected_plan.get("spending_changes", []),
        "lowest_balance_after_plan": projection.get("lowest_balance", ""),
        "lowest_balance_date_after_plan": projection.get("lowest_balance_date", ""),
        "ending_balance_after_plan": projection.get("ending_balance", ""),
    }


def validate_explanation(explanation):
    explanation = " ".join(str(explanation or "").split())
    if not explanation:
        raise ValueError("empty explanation")
    return explanation


def fallback_explanation(
    request,
    profile,
    selected_plan,
    selected_change_set,
    amount_safe_to_pay,
    earliest_date_for_full_payment,
):
    """Simple deterministic explanation when the LLM is unavailable."""
    currency = str(profile.get("home_currency", "")).strip()
    minimum_balance = str(profile.get("minimum_balance_to_keep", "")).strip()

    if not selected_plan:
        return (
            f"No safe eligible plan was found; only {currency} "
            f"{amount_safe_to_pay:g} is safe today without going below "
            f"the {currency} {minimum_balance} minimum."
        )

    method = str(selected_plan.get("plan_name", "")).strip()
    payments = selected_plan.get("payments", [])
    first_date = payments[0]["date"] if payments else ""
    changes_text = " with spending changes" if selected_change_set else ""

    return (
        f"Use {method}{changes_text}, starting {first_date}. "
        f"This keeps the projected balance above the {currency} "
        f"{minimum_balance} minimum; full payment is safe on "
        f"{earliest_date_for_full_payment or 'no date within the forecast'}."
    )
