"""Simple CSV loader for the Buy or Wait? dataset."""

import csv
import sys
from pathlib import Path


def load_data(dataset_dir=None):
    """Load required CSV files and return them as a dictionary of rows."""
    expected_fields = {
        "financial_profiles": [
            "user_id",
            "home_currency",
            "current_available_balance",
            "minimum_balance_to_keep",
            "financial_priorities",
            "expense_categories_to_protect",
            "expense_categories_user_is_willing_to_reduce",
            "expense_categories_user_is_willing_to_stop",
            "payment_methods_user_will_consider",
            "max_installment_months",
        ],
        "financial_events": [
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
        ],
        "exchange_rates": ["rate_date", "from_currency", "to_currency", "rate"],
        "requests": [
            "request_id",
            "user_id",
            "request_date",
            "request_type",
            "requested_amount",
            "desired_completion_date",
            "allows_partial_payment",
            "request_text",
        ],
        "request_payment_options": [
            "payment_option_id",
            "request_id",
            "payment_method",
            "payment_amount",
            "number_of_payments",
            "first_payment_date",
            "payment_frequency_days",
            "financing_fee",
            "total_payable_amount",
        ],
        "messages": [
            "message_id",
            "user_id",
            "request_id",
            "related_event_id",
            "sent_at",
            "source_type",
            "message_text",
        ],
        "images": ["image_id", "user_id", "request_id", "related_event_id"],
    }

    if dataset_dir is None:
        dataset_path = Path(__file__).resolve().parent.parent / "dataset"
    else:
        dataset_path = Path(dataset_dir).expanduser().resolve()

    # Stop early if the dataset folder itself is wrong.
    if not dataset_path.is_dir():
        print(f"Dataset path is not valid: {dataset_path}")
        sys.exit(1)

    data = {}

    for table_name, fields in expected_fields.items():
        csv_path = (dataset_path / f"{table_name}.csv").resolve()

        # File names are fixed, but keep the path check explicit for safety.
        if csv_path.parent != dataset_path or not csv_path.is_file():
            print(f"CSV path is not valid: {csv_path}")
            sys.exit(1)

        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)

                if not reader.fieldnames:
                    print(f"{csv_path.name} has no header row")
                    sys.exit(1)

                missing_fields = [
                    field for field in fields if field not in reader.fieldnames
                ]
                if missing_fields:
                    print(
                        f"{csv_path.name} is missing fields: "
                        + ", ".join(missing_fields)
                    )
                    sys.exit(1)

                data[table_name] = []
                for row in reader:
                    # Keep all CSV columns and trim simple unsafe characters.
                    clean_row = {}
                    for field, value in row.items():
                        if field is None:
                            continue
                        clean_field = field.replace("\x00", "").strip()
                        clean_value = str(value or "").replace("\x00", "").strip()
                        clean_row[clean_field] = clean_value

                    data[table_name].append(clean_row)
        except csv.Error as error:
            print(f"Could not read {csv_path.name}: {error}")
            sys.exit(1)
        except OSError as error:
            print(f"Could not open {csv_path.name}: {error}")
            sys.exit(1)

    return data
