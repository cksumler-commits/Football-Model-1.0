import psycopg
from collections import defaultdict


def get_connection():
    return psycopg.connect(
        dbname="Football-Model1.0",
        user="postgres",
        password="J-brown2026",
        host="localhost",
        port="5432"
    )


def main():
    conn = get_connection()
    cur = conn.cursor()

    issues = []
    total_plays = 0

    try:
        cur.execute(
            """
            SELECT
                id,
                game_name,
                series_number,
                play_number,
                quarter,
                game_time,
                down,
                distance,
                hash,
                rpn,
                yardline,
                yards_gained,
                result_reason
            FROM plays
            ORDER BY game_name, play_number, id;
            """
        )

        plays = cur.fetchall()
        total_plays = len(plays)

        if not plays:
            print("No plays found in the database.")
            return

        # Track play numbers within each game.
        play_numbers = defaultdict(list)

        for play in plays:
            (
                record_id,
                game_name,
                series_number,
                play_number,
                quarter,
                game_time,
                down,
                distance,
                hash_mark,
                rpn,
                yardline,
                yards_gained,
                result_reason
            ) = play

            play_numbers[(game_name, play_number)].append(record_id)

            # Missing or placeholder values.
            text_fields = {
                "Game Name": game_name,
                "Game Time": game_time,
                "Hash": hash_mark,
                "R/P/N": rpn,
                "Result Reason": result_reason
            }

            for field, value in text_fields.items():
                if value is None or not str(value).strip():
                    issues.append(
                        f"ID {record_id}: {field} is blank."
                    )
                elif str(value).strip().upper() == "N/A":
                    issues.append(
                        f"ID {record_id}: {field} is N/A."
                    )

            # Numeric fields that may need review.
            if series_number == 0:
                issues.append(
                    f"ID {record_id}: Series Number is 0."
                )

            if play_number <= 0:
                issues.append(
                    f"ID {record_id}: Play Number is not positive."
                )

            if quarter == 0:
                issues.append(
                    f"ID {record_id}: Quarter is unknown (0)."
                )
            elif quarter not in (1, 2, 3, 4):
                issues.append(
                    f"ID {record_id}: Invalid quarter {quarter}."
                )

            if down == 0:
                issues.append(
                    f"ID {record_id}: Down is unknown (0)."
                )
            elif down not in (1, 2, 3, 4):
                issues.append(
                    f"ID {record_id}: Invalid down {down}."
                )

            if distance == 0:
                issues.append(
                    f"ID {record_id}: Distance is 0; verify it."
                )

            if yardline == 0:
                issues.append("Yardline is 0 (invalid/unrecorded)")
            elif not -49 <= yardline <= 50:
                issues.append("Yardline is outside the allowed range")

            if yards_gained == 0:
                issues.append(
                    f"ID {record_id}: Yards Gained is 0; verify it."
                )

            normalized_rpn = str(rpn).strip().upper()

            if normalized_rpn not in (
                "R", "P", "N",
                "RUN", "PASS", "NO PLAY",
                "N/A"
            ):
                issues.append(
                    f"ID {record_id}: Unrecognized R/P/N value '{rpn}'."
                )

            normalized_hash = str(hash_mark).strip().upper()

            if normalized_hash not in (
                "LEFT", "MIDDLE", "RIGHT",
                "L", "M", "R", "N/A"
            ):
                issues.append(
                    f"ID {record_id}: Unrecognized hash '{hash_mark}'."
                )

        # Report duplicate play numbers.
        for (game_name, play_number), ids in play_numbers.items():
            if len(ids) > 1:
                issues.append(
                    f"Duplicate play number {play_number} in "
                    f"{game_name}: database IDs {ids}."
                )

        print("\nFOOTBALL INTELLIGENCE PLATFORM")
        print("DATA INTEGRITY AUDIT")
        print("=" * 60)
        print(f"Total plays checked: {total_plays}")
        print(f"Issues found: {len(issues)}")
        print("-" * 60)

        if not issues:
            print("No issues detected by these checks.")
        else:
            for issue in issues:
                print(f"- {issue}")

        print("\nAudit complete. No records were changed.")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()

