
import argparse
import csv
import io
import sys
from collections import Counter
from pathlib import Path

from roster_pdf_import import extract_pdf_text


FIELDS = [
    "Jersey Number",
    "Name",
    "Position",
    "Height",
    "Weight",
    "Class",
    "Experience",
    "Hometown",
    "High School",
    "Previous School",
]


def load_roster(pdf_path):
    """Extract a PDF using the existing roster PDF importer."""
    extracted_text = extract_pdf_text(str(pdf_path))

    reader = csv.DictReader(
        io.StringIO(extracted_text),
        delimiter="\t"
    )

    return list(reader)


def print_roster(pdf_path, records, show_empty=False):
    print("\n" + "=" * 90)
    print(f"FILE: {pdf_path.name}")
    print("=" * 90)

    print(f"TOTAL EXTRACTED PLAYERS: {len(records)}")

    blank_counts = Counter()
    jersey_counts = Counter()

    for index, record in enumerate(records, start=1):
        jersey = record.get("Jersey Number", "").strip()
        name = record.get("Name", "").strip()

        if jersey:
            jersey_counts[jersey] += 1

        print("\n" + "-" * 90)
        print(f"PLAYER {index:03} | #{jersey or 'UNKNOWN'} | {name or 'NAME NOT EXTRACTED'}")
        print("-" * 90)

        for field in FIELDS:
            value = record.get(field, "")
            value = value.strip() if value else ""

            if not value:
                blank_counts[field] += 1

                if show_empty:
                    print(f"{field:18}: [BLANK]")
            else:
                print(f"{field:18}: {value}")

    print("\n" + "=" * 90)
    print("EXTRACTION SUMMARY")
    print("=" * 90)

    print(f"Total records: {len(records)}")

    print("\nBlank extracted values:")
    for field in FIELDS:
        print(f"{field:18}: {blank_counts[field]}")

    duplicates = {
        jersey: count
        for jersey, count in jersey_counts.items()
        if count > 1
    }

    print("\nRepeated jersey numbers:")
    if duplicates:
        for jersey, count in sorted(
            duplicates.items(),
            key=lambda item: int(item[0]) if item[0].isdigit() else 999
        ):
            print(f"#{jersey}: {count} players")
    else:
        print("None detected.")

    print("\nIMPORTANT:")
    print("Blank values indicate fields the extractor did not return.")
    print("They do not automatically mean the original PDF lacked that information.")


def main():
    parser = argparse.ArgumentParser(
        description="Readable diagnostic runner for roster PDF extraction."
    )

    parser.add_argument(
        "pdfs",
        nargs="+",
        help="One or more PDF file paths."
    )

    parser.add_argument(
        "--show-empty",
        action="store_true",
        help="Display blank fields for every player."
    )

    args = parser.parse_args()

    for supplied_path in args.pdfs:
        pdf_path = Path(supplied_path)

        if not pdf_path.exists():
            print(f"\nFILE NOT FOUND: {pdf_path}")
            continue

        if pdf_path.suffix.lower() != ".pdf":
            print(f"\nNOT A PDF: {pdf_path}")
            continue

        try:
            records = load_roster(pdf_path)
            print_roster(
                pdf_path,
                records,
                show_empty=args.show_empty
            )

        except Exception as error:
            print("\n" + "=" * 90)
            print(f"EXTRACTION FAILED: {pdf_path.name}")
            print("=" * 90)
            print(f"{type(error).__name__}: {error}")


if __name__ == "__main__":
    main()
