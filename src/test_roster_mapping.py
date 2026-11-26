
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from roster_import_parser import parse_roster_clipboard
from roster_import_mapping import RosterImportMappingDialog


app = QApplication(sys.argv)


try:
    result = parse_roster_clipboard()

    print("PIPELINE:", result.get("pipeline_type"))
    print("ORIGINAL MAPPING:", result.get("column_mapping"))
    print("INFERRED MAPPING:", (result.get("analysis") or {}).get("mapping"))

    print("\n--- FIRST FIVE ORIGINAL RECORDS ---")
    for record in result.get("records", [])[:5]:
        print({
            "jersey_number": record.get("jersey_number"),
            "full_name": record.get("full_name"),
            "position": record.get("position"),
            "custom_fields": record.get("custom_fields"),
        })

    print("\n--- HEADERED SOURCE TRACKING ---")

    for record in result.get("records", [])[:5]:
        print({
            "player": record.get("full_name"),
            "source_row_index": record.get("source_row_index"),
            "raw_row": record.get("raw_row"),
            "compound_interpretations": record.get(
            "compound_interpretations"
            ),
        })

    print("PIPELINE:", result.get("pipeline_type"))





    print("\n--- UNRESOLVED RECORD DETAILS ---")
    for index in [2, 4]:
        original_records = result.get("records", [])

        if index < len(original_records):
            record = original_records[index]

            print(f"\nRECORD {index}:")
            print("RAW ROW:", record.get("raw_row"))
            print("CUSTOM FIELDS:", record.get("custom_fields"))
            print("COMPOUND INTERPRETATIONS:", record.get("compound_interpretations"))
            print("REVIEW WARNINGS:", record.get("review_warnings"))

    if not result.get("records"):
        QMessageBox.warning(
            None,
            "Import Error",
            "No player records were detected."
        )
        sys.exit(1)

    dialog = RosterImportMappingDialog(result)

    if dialog.exec():

        print("\n--- MAPPING RESULTS ---")
        print("Records:", len(dialog.records))

        print("\nUPDATED COLUMN MAPPING:")
        print(dialog.import_result.get("column_mapping"))

        print("\nFIRST FIVE REBUILT RECORDS:")
        for record in dialog.import_result.get("records", [])[:5]:
            print({
                "jersey_number": record.get("jersey_number"),
                "full_name": record.get("full_name"),
                "position": record.get("position"),
                "hometown": record.get("hometown"),
                "high_school": record.get("high_school"),
                "custom_fields": record.get("custom_fields"),
            })

        # --------------------------------------------------
        # REBUILT DATASET QUALITY CHECK
        # --------------------------------------------------

        rebuilt_records = dialog.import_result.get("records", [])

        records_with_warnings = [
            record for record in rebuilt_records
            if record.get("review_warnings")
        ]

        records_with_duplicates = [
            record for record in rebuilt_records
            if record.get("duplicate_columns")
        ]

        records_with_custom_fields = [
            record for record in rebuilt_records
            if record.get("custom_fields")
        ]

        missing_high_school = [
            record for record in rebuilt_records
            if not record.get("high_school")
        ]

        missing_hometown = [
            record for record in rebuilt_records
            if not record.get("hometown")
        ]

        print("\n--- REBUILT DATASET QUALITY CHECK ---")
        print("Total records:", len(rebuilt_records))
        print("Records with review warnings:", len(records_with_warnings))
        print("Records with duplicate columns:", len(records_with_duplicates))
        print("Records with custom fields:", len(records_with_custom_fields))
        print("Records with missing high school:", len(missing_high_school))
        print("Records with missing hometown:", len(missing_hometown))

        # --------------------------------------------------
        # AKRAM ELNAGMI CLASSIFICATION DEBUG
        # --------------------------------------------------

        from roster_import_parser import (
            _classify_compound_component,
            _looks_like_school_name,
        )

        for record in rebuilt_records:
            if record.get("full_name") == "Akram Elnagmi":
                print("\n--- AKRAM ELNAGMI CLASSIFICATION DEBUG ---")

                print(
                    "INTERPRETATION:",
                    record.get("compound_interpretations")
                )

                components = [
                    "Bristol, UK",
                    "NFL Academy (UK)",
                ]

                for component in components:
                    print(
                        component,
                        "| CLASSIFICATION:",
                        _classify_compound_component(component),
                        "| SCHOOL NAME:",
                        _looks_like_school_name(component),
                    )

        # --------------------------------------------------
        # FIRST TEN RECORDS NEEDING REVIEW
        # --------------------------------------------------

        print("\n--- FIRST TEN RECORDS NEEDING REVIEW ---")

        needs_review = [
            record for record in rebuilt_records
            if (
                record.get("review_warnings")
                or record.get("custom_fields")
                or record.get("duplicate_columns")
            )
        ]

        for record in needs_review[:10]:
            print({
                "player": record.get("full_name"),
                "jersey_number": record.get("jersey_number"),
                "hometown": record.get("hometown"),
                "high_school": record.get("high_school"),
                "custom_fields": record.get("custom_fields"),
                "warnings": record.get("review_warnings"),
                "duplicates": record.get("duplicate_columns"),
            })

    else:
        print("Mapping dialog canceled.")

except Exception as error:
    QMessageBox.critical(
        None,
        "Test Error",
        str(error)
    )
    raise