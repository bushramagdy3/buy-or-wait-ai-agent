import json
from datetime import datetime

from code.event_utils import EVENT_FIELDS, validate_event_values
from code.llm_utils import invoke_with_rate_limit_retry
from code.settings import OPENAI_API_KEY


ALLOWED_STATUSES = [
    "settled",
    "pending",
    "scheduled",
    "failed",
    "cancelled",
    "unrealized",
]

STATUS_ALIASES = {
    "complete": "settled",
    "completed": "settled",
    "closed": "settled",
    "posted": "settled",
    "received": "settled",
    "initiated": "pending",
    "processing": "pending",
    "open": "pending",
    "outstanding": "pending",
    "not completed": "pending",
    "not settled": "pending",
    "declined": "failed",
    "rejected": "failed",
    "canceled": "cancelled",
    "not sold": "unrealized",
}


def apply_message_event_updates(events, messages):
    """Let messages override events, then apply validated updates/deletes."""
    linked_messages = linked_event_messages(messages)
    if not linked_messages:
        print("  Message updates: no linked event messages.")
        return events

    linked_event_ids = {
        str(message.get("related_event_id", "")).strip()
        for message in linked_messages
    }
    linked_events = [
        event
        for event in events
        if str(event.get("event_id", "")).strip() in linked_event_ids
    ]
    if not linked_events:
        print("  Message updates: linked events were not found.")
        return events

    print(
        "  Message updates: checking "
        f"{len(linked_messages)} messages for {len(linked_events)} events."
    )

    try:
        changes = get_message_event_changes(linked_events, linked_messages)
    except Exception as error:
        print(f"Could not apply message event updates: {error}")
        return events

    print(f"  Message updates: applying {len(changes)} event changes.")

    updated_events = []
    for event in events:
        event_id = str(event.get("event_id", "")).strip()
        change = changes.get(event_id)

        if not change:
            updated_events.append(event)
            continue

        action = str(change.get("action", "")).strip()
        if action == "delete":
            continue

        if action == "update":
            updated_event = dict(event)
            for key, value in (change.get("changes") or {}).items():
                if key in EVENT_FIELDS and key not in ["event_id", "user_id"]:
                    try:
                        candidate = dict(updated_event)
                        candidate[key] = clean_message_value(key, value)
                        validate_event_values(candidate)
                        updated_event = candidate
                    except Exception as error:
                        print(
                            "Skipping invalid message field for "
                            f"{event_id}: {key}={value} ({error})"
                        )

            updated_events.append(updated_event)
            continue

        print(f"Skipping unknown message action for {event_id}: {action}")
        updated_events.append(event)

    return updated_events


def linked_event_messages(messages):
    """Only event-linked messages can safely update existing event rows."""
    return [
        message
        for message in messages
        if str(message.get("related_event_id", "")).strip()
    ]


def get_message_event_changes(events, messages):
    """Ask the LLM for event edits. Messages are treated as source of truth."""
    from langchain_openai import ChatOpenAI
    from pydantic import BaseModel

    class FieldChange(BaseModel):
        field: str
        value: str

    class EventChange(BaseModel):
        event_id: str
        action: str
        changes: list[FieldChange]

    class EventChanges(BaseModel):
        event_changes: list[EventChange]

    model_name = "gpt-4o-mini"
    llm = ChatOpenAI(
        model=model_name,
        temperature=0,
        openai_api_key=OPENAI_API_KEY,
    ).with_structured_output(EventChanges, include_raw=True)

    compact_events = [
        {field: str(event.get(field, "") or "") for field in EVENT_FIELDS}
        for event in events
    ]
    compact_messages = [
        {
            "message_id": str(message.get("message_id", "") or ""),
            "related_event_id": str(message.get("related_event_id", "") or ""),
            "sent_at": str(message.get("sent_at", "") or ""),
            "source_type": str(message.get("source_type", "") or ""),
            "message_text": str(message.get("message_text", "") or ""),
        }
        for message in messages
    ]

    prompt = (
        "Messages are the source of truth. Compare the financial events against "
        "the linked user messages. Return event_changes as a list. Each item "
        "must have event_id, action='update' or action='delete', and changes as a list of "
        "{field, value}. For deletes, use an empty changes list. Only change "
        "events when a message clearly amends, confirms, delays, cancels, or "
        "corrects that event. Do not include unchanged events. If there are no "
        "changes, return an empty event_changes list. Use only these status values: "
        f"{', '.join(ALLOWED_STATUSES)}. Dates must be YYYY-MM-DD. Do not use "
        "TBD, unknown, completed, initiated, closed, or other free-text values; "
        "leave a field unchanged if the exact valid value is not known. Only "
        "return event_ids that appear in the Events list."
    )

    result = invoke_with_rate_limit_retry(
        llm,
        [
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\nEvents:\n{json.dumps(compact_events)}\n\n"
                    f"Messages:\n{json.dumps(compact_messages)}"
                ),
            }
        ],
        usage_step="message_event_updates",
        model_name=model_name,
    )

    if isinstance(result, dict):
        if result.get("parsing_error"):
            raise ValueError(result["parsing_error"])
        result = result.get("parsed")
    if result is None:
        raise ValueError("LLM did not return parsed event changes")

    if hasattr(result, "model_dump"):
        raw_changes = result.model_dump()["event_changes"]
    else:
        raw_changes = result.dict()["event_changes"]

    return validate_message_changes(raw_changes)


def validate_message_changes(raw_changes):
    """Normalize and validate the LLM's update/delete instructions."""
    changes = {}
    if not isinstance(raw_changes, list):
        return changes

    for change in raw_changes:
        if not isinstance(change, dict):
            continue

        event_id = str(change.get("event_id", "")).strip()
        if not event_id:
            continue

        action = str(change.get("action", "")).strip()
        event_changes = change.get("changes")

        if action == "delete":
            changes[event_id] = {"action": "delete", "changes": None}
        elif action == "update" and isinstance(event_changes, list):
            clean_changes = {
                str(item.get("field", "")).strip(): str(
                    item.get("value", "") or ""
                ).strip()
                for item in event_changes
                if str(item.get("field", "")).strip() in EVENT_FIELDS
                and str(item.get("field", "")).strip() not in ["event_id", "user_id"]
            }
            if clean_changes:
                changes[event_id] = {
                    "action": "update",
                    "changes": clean_changes,
                }

    return changes


def clean_message_value(field, value):
    """Normalize common LLM wording before validating an event update."""
    value = str(value or "").strip()

    if field == "status":
        return normalize_status(value)
    if field in ["event_date", "settlement_date"]:
        return normalize_date(value)

    return value


def normalize_status(value):
    status = value.strip().lower()
    if status in ALLOWED_STATUSES:
        return status
    if status in STATUS_ALIASES:
        return STATUS_ALIASES[status]
    raise ValueError("invalid status")


def normalize_date(value):
    if value.strip().lower() in ["tbd", "unknown", "none", "not approved"]:
        raise ValueError("invalid date")

    datetime.strptime(value, "%Y-%m-%d")
    return value
