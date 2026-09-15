import csv
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CODE_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from code.data_loader import load_data
from code.image_preprocessor import preprocess_images
from code.resolver import resolve_request


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

SCORED_COLUMNS = [
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


def main():
    """Resolve sample requests and print predicted vs expected cell accuracy."""
    try:
        preprocess_images()
        data = load_data()
        sample_requests = load_sample_requests()
    except SystemExit as error:
        print(f"Setup failed. Exit code: {error.code}")
        return
    except Exception as error:
        print(f"Setup failed: {error}")
        return

    total_correct = 0
    total_cells = 0
    column_scores = {column: {"correct": 0, "total": 0} for column in SCORED_COLUMNS}

    for sample in sample_requests:
        request_id = str(sample.get("request_id", "")).strip()
        print(f"\nRequest {request_id}")

        try:
            predicted = resolve_request(sample, data)
        except Exception as error:
            print(f"  Could not resolve request: {error}")
            predicted = {"request_id": request_id}

        for column in SCORED_COLUMNS:
            predicted_value = predicted.get(column, "")
            expected_value = sample.get(column, "")
            is_match = cells_match(column, predicted_value, expected_value)

            total_cells += 1
            column_scores[column]["total"] += 1
            if is_match:
                total_correct += 1
                column_scores[column]["correct"] += 1

            print(f"  {column}: {'OK' if is_match else 'MISS'}")
            print(f"    predicted: {predicted_value}")
            print(f"    expected : {expected_value}")

    print_summary(total_correct, total_cells, column_scores)


def load_sample_requests():
    sample_path = DATASET_DIR / "sample_requests.csv"
    if not sample_path.is_file():
        raise FileNotFoundError(f"missing sample file: {sample_path}")

    with sample_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = [column for column in OUTPUT_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise ValueError("sample_requests.csv missing: " + ", ".join(missing))
        return [clean_row(row) for row in reader]


def clean_row(row):
    return {
        str(key or "").replace("\x00", "").strip(): str(value or "")
        .replace("\x00", "")
        .strip()
        for key, value in row.items()
        if key is not None
    }


def cells_match(column, predicted_value, expected_value):
    if column == "amount_safe_to_pay":
        return normalize_amount(predicted_value) == normalize_amount(expected_value)
    if column == "payment_plan":
        return normalize_payment_plan(predicted_value) == normalize_payment_plan(
            expected_value
        )
    if column == "spending_changes_needed":
        return normalize_spending_changes(predicted_value) == normalize_spending_changes(
            expected_value
        )
    return normalize_text(predicted_value) == normalize_text(expected_value)


def normalize_payment_plan(value):
    value = normalize_text(value)
    if value == "none":
        return value

    parts = []
    for item in value.split("|"):
        if ":" not in item:
            parts.append(item.strip())
            continue
        date, amount = item.split(":", 1)
        parts.append(f"{date.strip()}:{normalize_amount(amount)}")
    return "|".join(parts)


def normalize_spending_changes(value):
    value = normalize_text(value)
    if value == "none":
        return value

    parts = []
    for item in value.split("|"):
        pieces = [piece.strip() for piece in item.split(":")]
        if len(pieces) == 3 and pieces[0] == "reduce_to":
            pieces[2] = normalize_amount(pieces[2])
        parts.append(":".join(pieces))
    return "|".join(parts)


def normalize_amount(value):
    try:
        amount = Decimal(str(value or "").replace(",", "").strip())
    except InvalidOperation:
        return normalize_text(value)

    return str(amount.quantize(Decimal("0.01")).normalize())


def normalize_text(value):
    return " ".join(str(value or "").strip().split())


def print_summary(total_correct, total_cells, column_scores):
    accuracy = total_correct / total_cells if total_cells else 0
    print("\nFinal Cell Accuracy")
    print(f"  total: {total_correct}/{total_cells} = {accuracy:.2%}")

    print("\nColumn Accuracy")
    for column, score in column_scores.items():
        column_accuracy = score["correct"] / score["total"] if score["total"] else 0
        print(
            f"  {column}: {score['correct']}/{score['total']} = "
            f"{column_accuracy:.2%}"
        )


if __name__ == "__main__":
    main()
