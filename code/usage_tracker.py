import os
from pathlib import Path


INPUT_COST_PER_MILLION = 0.15
OUTPUT_COST_PER_MILLION = 0.60

STEPS = {
    "image_event_repair": {
        "name": "Image event repair",
        "provider": "OpenAI",
        "default_model": lambda: os.getenv("EVENT_REPAIR_MODEL", "gpt-4o-mini"),
    },
    "message_event_updates": {
        "name": "Message event updates",
        "provider": "OpenAI",
        "default_model": lambda: "gpt-4o-mini",
    },
    "decision_explanation": {
        "name": "Decision explanation",
        "provider": "OpenAI",
        "default_model": lambda: os.getenv("EXPLANATION_MODEL", "gpt-4o-mini"),
    },
}

_usage = {}


def reset_usage():
    """Start a fresh in-memory usage count for one program run."""
    _usage.clear()
    for step in STEPS:
        _usage[step] = {
            "models": set(),
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }


def record_llm_usage(step, response, model_name=""):
    """Record one successful LLM response using its returned usage metadata."""
    if step not in _usage:
        reset_usage()

    usage = extract_usage_metadata(response)
    input_tokens = to_int(usage.get("input_tokens", 0))
    output_tokens = to_int(usage.get("output_tokens", 0))
    total_tokens = to_int(usage.get("total_tokens", input_tokens + output_tokens))

    _usage[step]["calls"] += 1
    _usage[step]["input_tokens"] += input_tokens
    _usage[step]["output_tokens"] += output_tokens
    _usage[step]["total_tokens"] += total_tokens

    model_name = str(model_name or "").strip()
    if model_name:
        _usage[step]["models"].add(model_name)


def extract_usage_metadata(response):
    """Handle LangChain raw messages and structured-output wrappers."""
    raw = response.get("raw") if isinstance(response, dict) else response
    if raw is None:
        raw = response

    usage = getattr(raw, "usage_metadata", None)
    if usage:
        return normalize_usage_dict(usage)

    metadata = getattr(raw, "response_metadata", None) or {}
    token_usage = metadata.get("token_usage") or metadata.get("usage") or {}
    return normalize_usage_dict(token_usage)


def normalize_usage_dict(usage):
    """Normalize common OpenAI/LangChain token field names."""
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    total_tokens = usage.get("total_tokens", 0)
    if not total_tokens:
        total_tokens = to_int(input_tokens) + to_int(output_tokens)

    return {
        "input_tokens": to_int(input_tokens),
        "output_tokens": to_int(output_tokens),
        "total_tokens": to_int(total_tokens),
    }


def write_usage_report(request_count, report_path=None):
    """Write evaluation/usage_report.md after the full dataset run finishes."""
    if report_path is None:
        report_path = Path(__file__).resolve().parent / "evaluation" / "usage_report.md"

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        format_usage_report(request_count),
        encoding="utf-8",
    )
    print(f"Wrote usage report to {report_path}")


def format_usage_report(request_count):
    """Build the markdown usage report from the current counters."""
    request_count = max(0, to_int(request_count))
    rows = []
    totals = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }

    for step, info in STEPS.items():
        item = _usage.get(step)
        if item is None:
            reset_usage()
            item = _usage[step]

        cost = estimated_cost(item["input_tokens"], item["output_tokens"])
        models = sorted(item["models"]) or [info["default_model"]()]
        rows.append(
            "| {name} | {provider} | {models} | {calls} | {input_tokens} | {output_tokens} | "
            "{total_tokens} | {avg_tokens} | {cost} |".format(
                name=info["name"],
                provider=info["provider"],
                models=", ".join(f"`{model}`" for model in models),
                calls=item["calls"],
                input_tokens=item["input_tokens"],
                output_tokens=item["output_tokens"],
                total_tokens=item["total_tokens"],
                avg_tokens=format_average(item["total_tokens"], request_count),
                cost=format_cost(cost),
            )
        )

        for key in totals:
            totals[key] += item[key]

    total_cost = estimated_cost(totals["input_tokens"], totals["output_tokens"])

    return "\n".join(
        [
            "# Usage Report",
            "",
            "Generated automatically after running `code/main.py` on the full dataset.",
            "",
            "## Pricing",
            "",
            "| Provider | Model | Input | Output |",
            "|---|---|---:|---:|",
            "| OpenAI | `gpt-4o-mini` | $0.15 / 1M tokens | $0.60 / 1M tokens |",
            "",
            "## Usage By Step",
            "",
            f"Requests in dataset: `{request_count}`",
            "",
            "| Step | Provider | Model(s) | Successful calls | Input tokens | Output tokens | Total tokens | Avg tokens/request | Estimated cost |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            "## Overall Totals",
            "",
            "| Requests | Successful calls | Input tokens | Output tokens | Total tokens | Avg input/request | Avg output/request | Avg total/request | Estimated total cost | Estimated cost/request |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            "| {requests} | {calls} | {input_tokens} | {output_tokens} | "
            "{total_tokens} | {avg_input} | {avg_output} | {avg_total} | "
            "{total_cost} | {avg_cost} |".format(
                requests=request_count,
                calls=totals["calls"],
                input_tokens=totals["input_tokens"],
                output_tokens=totals["output_tokens"],
                total_tokens=totals["total_tokens"],
                avg_input=format_average(totals["input_tokens"], request_count),
                avg_output=format_average(totals["output_tokens"], request_count),
                avg_total=format_average(totals["total_tokens"], request_count),
                total_cost=format_cost(total_cost),
                avg_cost=format_cost(total_cost / request_count if request_count else 0),
            ),
            "",
            "Token counts come from the usage metadata returned by each successful `llm.invoke()` response.",
            "If `output.csv` already contains valid rows, those skipped requests do not make new LLM calls in that run.",
            "",
        ]
    )


def estimated_cost(input_tokens, output_tokens):
    input_cost = to_int(input_tokens) * INPUT_COST_PER_MILLION / 1_000_000
    output_cost = to_int(output_tokens) * OUTPUT_COST_PER_MILLION / 1_000_000
    return input_cost + output_cost


def format_average(value, request_count):
    if not request_count:
        return "0.00"
    return f"{to_int(value) / request_count:.2f}"


def format_cost(value):
    return f"${float(value):.6f}"


def to_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


reset_usage()
