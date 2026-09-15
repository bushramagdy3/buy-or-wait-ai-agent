import csv
from pathlib import Path

from code.data_loader import load_data
from code.image_preprocessor import preprocess_images
from code.resolver import resolve_request
from code.usage_tracker import reset_usage, write_usage_report


OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

VALID_STATUSES = {
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable",
}

VALID_METHODS = {
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
}


def main():
    """Load existing answers, resolve missing requests, and save output.csv."""
    output_path = Path(__file__).resolve().parent.parent / "output.csv"
    resolved_rows = []
    resolved_ids = set()
    load_existing_rows(output_path, resolved_rows, resolved_ids)

    try:
        preprocess_images()
        data = load_data()
    except SystemExit as error:
        print(f"Setup failed. Exit code: {error.code}")
        return
    except Exception as error:
        print(f"Setup failed: {error}")
        return

    reset_usage()
    requests = data.get("requests", [])
    request_count = len(requests)
    remaining_count = sum(
        1
        for request in requests
        if str(request.get("request_id", "")).strip()
        and str(request.get("request_id", "")).strip() not in resolved_ids
    )
    print(f"Loaded {len(resolved_rows)} valid existing output rows.")
    print(f"Resolving {remaining_count} of {request_count} requests.")

    for index, request in enumerate(requests, start=1):
        request_id = str(request.get("request_id", "")).strip()
        if not request_id:
            print(f"[{index}/{request_count}] Skipping request with missing id.")
            continue
        if request_id in resolved_ids:
            print(f"[{index}/{request_count}] Skipping {request_id}: already resolved.")
            continue

        try:
            print(f"[{index}/{request_count}] Resolving {request_id}...")
            row = resolve_request(request, data)

            clean_row = {
                column: str(row.get(column, "")).strip()
                for column in OUTPUT_COLUMNS
            }

            resolved_rows.append(clean_row)
            resolved_ids.add(request_id)
            print(f"[{index}/{request_count}] Resolved {request_id}.")
        except Exception as error:
            print(f"Could not resolve {request_id}: {error}")
            continue

    save_rows(output_path, resolved_rows)
    write_usage_report(request_count)


def load_existing_rows(output_path, resolved_rows, resolved_ids):
    """Append valid existing output rows to resolved_rows."""
    output_path = Path(output_path)
    if not output_path.exists():
        return

    try:
        with output_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                try:
                    if is_blank_output_row(row):
                        continue

                    validate_row(row)
                    request_id = str(row["request_id"]).strip()
                    if request_id in resolved_ids:
                        continue

                    clean_row = {
                        column: str(row.get(column, "")).strip()
                        for column in OUTPUT_COLUMNS
                    }

                    resolved_rows.append(clean_row)
                    resolved_ids.add(request_id)
                except Exception as error:
                    request_id = str(row.get("request_id", "")).strip() or "unknown"
                    print(f"Skipping existing row {request_id}: {error}")
                    continue
    except Exception as error:
        print(f"Could not read existing output.csv: {error}")


def is_blank_output_row(row):
    """Skip empty output.csv template rows without noisy warnings."""
    return all(
        not str(row.get(column, "")).strip()
        for column in OUTPUT_COLUMNS
        if column != "request_id"
    )


def validate_row(row, request=None):
    """Raise an error if an output row is not valid enough to save."""
    if not isinstance(row, dict):
        raise ValueError("row must be a dictionary")

    for column in OUTPUT_COLUMNS:
        if column not in row:
            raise ValueError(f"missing column: {column}")

    request_id = str(row.get("request_id", "")).strip()
    if not request_id:
        raise ValueError("request_id is required")

    amount_safe_to_pay = float(str(row.get("amount_safe_to_pay", "")).strip())
    if amount_safe_to_pay < 0:
        raise ValueError("amount_safe_to_pay cannot be negative")

    if request is not None:
        if request_id != str(request.get("request_id", "")).strip():
            raise ValueError("request_id does not match request")
        requested_amount = float(str(request.get("requested_amount", "")).strip())
        if amount_safe_to_pay > requested_amount:
            raise ValueError("amount_safe_to_pay is above requested_amount")

    if str(row.get("affordability_status", "")).strip() not in VALID_STATUSES:
        raise ValueError("invalid affordability_status")

    if str(row.get("recommended_payment_method", "")).strip() not in VALID_METHODS:
        raise ValueError("invalid recommended_payment_method")

    if not str(row.get("payment_plan", "")).strip():
        raise ValueError("payment_plan is required")

    if not str(row.get("spending_changes_needed", "")).strip():
        raise ValueError("spending_changes_needed is required")

    if not str(row.get("decision_explanation", "")).strip():
        raise ValueError("decision_explanation is required")


def save_rows(output_path, resolved_rows):
    """Write resolved rows to output.csv with one row per request_id."""
    try:
        with output_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(resolved_rows)
        print(f"Saved {len(resolved_rows)} rows to {output_path}")
    except Exception as error:
        print(f"Could not save output.csv: {error}")


if __name__ == "__main__":
    main()
