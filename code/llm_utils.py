import time

from code.usage_tracker import record_llm_usage


def invoke_with_rate_limit_retry(
    llm,
    messages,
    max_attempts=3,
    wait_seconds=20,
    usage_step="",
    model_name="",
):
    """Call an LLM and retry after a short wait if the API rate-limits us."""
    for attempt in range(1, max_attempts + 1):
        try:
            response = llm.invoke(messages)
            if usage_step:
                record_llm_usage(usage_step, response, model_name)
            return response
        except Exception as error:
            if not is_rate_limit_error(error) or attempt == max_attempts:
                raise

            step_text = f" during {usage_step}" if usage_step else ""
            print(
                f"Rate limit hit{step_text}. Waiting {wait_seconds} seconds "
                f"before retry {attempt + 1}/{max_attempts}."
            )
            time.sleep(wait_seconds)


def is_rate_limit_error(error):
    """Detect rate-limit errors without depending on one provider class."""
    error_text = str(error).lower()
    error_name = error.__class__.__name__.lower()
    return (
        "ratelimit" in error_name
        or "rate_limit" in error_text
        or "rate limit" in error_text
        or "error code: 429" in error_text
        or "status code: 429" in error_text
    )
