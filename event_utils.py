from datetime import datetime
from pathlib import Path


EVENT_FIELDS = [
    "event_id",
    "user_id",
    "event_type",
    "description",
    "category",
    "direction",
    "amount",
    "currency",
    "event_date",
    "settlement_date",
    "status",
    "linked_event_id",
    "flexibility",
    "minimum_allowed_amount",
]

REQUIRED_EVENT_FIELDS = [
    "event_id",
    "user_id",
    "event_type",
    "description",
    "category",
    "direction",
    "amount",
    "currency",
    "event_date",
    "settlement_date",
    "status",
    "flexibility",
]


def find_image_path(image_id):
    """Return the preprocessed image path when available, otherwise raw media."""
    image_name = str(image_id or "").strip()
    if not image_name:
        return ""

    media_path = Path(__file__).resolve().parent.parent / "dataset" / "media"
    for image_dir in [media_path / "preprocessed_images", media_path / "images"]:
        if not image_dir.is_dir():
            continue

        matches = sorted(image_dir.glob(f"{image_name}.*"))
        if matches:
            return str(matches[0])

    return ""


def has_missing_required_fields(event):
    return any(not str(event.get(field, "")).strip() for field in REQUIRED_EVENT_FIELDS)


def parse_date(value):
    value = str(value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def split_list(value):
    """Split pipe-separated CSV fields into a clean list."""
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def to_float(value):
    """Convert a CSV number into a float."""
    return float(str(value or "0").strip())


def safe_amount(event):
    amount = str(event.get("amount", "")).strip()
    if not amount:
        return None
    return to_float(amount)


def event_date_for(event):
    return parse_date(event.get("settlement_date", "")) or parse_date(
        event.get("event_date", "")
    )


def validate_event_values(event):
    """Validate common event values after an LLM suggests changes."""
    if event["direction"] not in ["debit", "credit", "non_cash"]:
        raise ValueError("invalid direction")
    if event["status"] not in [
        "settled",
        "pending",
        "scheduled",
        "failed",
        "cancelled",
        "unrealized",
    ]:
        raise ValueError("invalid status")

    to_float(event["amount"])
    parse_date(event["event_date"])
    parse_date(event["settlement_date"])
    if event["minimum_allowed_amount"]:
        to_float(event["minimum_allowed_amount"])
