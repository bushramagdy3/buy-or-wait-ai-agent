import base64
import json
import mimetypes
import os
from pathlib import Path

from code.event_utils import (
    EVENT_FIELDS,
    has_missing_required_fields,
    validate_event_values,
)
from code.llm_utils import invoke_with_rate_limit_retry
from code.settings import OPENAI_API_KEY


def fill_missing_event_fields(events, images):
    """Use linked images to repair events that are missing important fields."""
    images_by_event_id = {
        str(image.get("related_event_id", "")).strip(): image
        for image in images
        if str(image.get("related_event_id", "")).strip()
    }

    repaired_events = []
    for event in events:
        image = images_by_event_id.get(str(event.get("event_id", "")).strip())
        if has_missing_required_fields(event) and image and image.get("image_path"):
            try:
                repaired_events.append(repair_event_from_image(event, image["image_path"]))
                continue
            except Exception as error:
                print(f"Could not repair {event.get('event_id', '')}: {error}")

        repaired_events.append(event)

    return repaired_events


def repair_event_from_image(event, image_path):
    """Ask a vision LLM for a full event, then validate before replacing."""
    from langchain_openai import ChatOpenAI
    from pydantic import BaseModel, Field

    class EventModel(BaseModel):
        event_id: str = Field(description="Original event_id")
        user_id: str
        event_type: str
        description: str
        category: str
        direction: str
        amount: str
        currency: str
        event_date: str
        settlement_date: str
        status: str
        linked_event_id: str
        flexibility: str
        minimum_allowed_amount: str

    image_file = Path(image_path)
    mime_type = mimetypes.guess_type(str(image_file))[0] or "image/png"
    image_data = base64.b64encode(image_file.read_bytes()).decode("utf-8")
    current_event = {field: str(event.get(field, "") or "") for field in EVENT_FIELDS}

    model_name = os.getenv("EVENT_REPAIR_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(
        model=model_name,
        temperature=0,
        openai_api_key=OPENAI_API_KEY,
    ).with_structured_output(EventModel, include_raw=True)

    # The image is evidence only; preserve existing values unless it clarifies blanks.
    repaired = invoke_with_rate_limit_retry(
        llm,
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Fill missing financial event fields using the image. "
                            "Return one complete event. Preserve existing non-empty "
                            "values unless the image clearly corrects them. Use an "
                            "empty string for any field that is still unknown.\n\n"
                            f"Current event:\n{json.dumps(current_event)}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                    },
                ],
            }
        ],
        usage_step="image_event_repair",
        model_name=model_name,
    )

    if isinstance(repaired, dict):
        if repaired.get("parsing_error"):
            raise ValueError(repaired["parsing_error"])
        repaired = repaired.get("parsed")
    if repaired is None:
        raise ValueError("LLM did not return a parsed event")

    if hasattr(repaired, "model_dump"):
        repaired_event = repaired.model_dump()
    else:
        repaired_event = repaired.dict()

    return validate_repaired_event(event, repaired_event)


def validate_repaired_event(original_event, repaired_event):
    """Keep only validated LLM output, preserving event identity."""
    clean_event = {
        field: str(repaired_event.get(field, "") or "").strip()
        for field in EVENT_FIELDS
    }

    if clean_event["event_id"] != str(original_event.get("event_id", "")).strip():
        raise ValueError("LLM changed event_id")
    if clean_event["user_id"] != str(original_event.get("user_id", "")).strip():
        raise ValueError("LLM changed user_id")
    if has_missing_required_fields(clean_event):
        raise ValueError("LLM result still has missing required fields")

    validate_event_values(clean_event)
    return clean_event
