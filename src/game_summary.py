import psycopg


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

    try:
        print("GAME SUMMARY REPORT")
        print("=" * 60)

        game_name = input("Enter Game Name: ").strip()

        if not game_name:
            print("Game name cannot be blank.")
            return

        # Normalize common R/P/N labels into consistent categories.
        normalized_type = """
            CASE
                WHEN UPPER(TRIM(rpn)) IN ('R', 'RUN')
                    THEN 'Run'
                WHEN UPPER(TRIM(rpn)) IN ('P', 'PASS')
                    THEN 'Pass'
                WHEN UPPER(TRIM(rpn)) IN (
                    'N', 'NO PLAY', 'NO-PLAY', 'NOPLAY'
                )
                    THEN 'No Play'
                ELSE 'Unknown / Other'
            END
        """

        # Overall report totals.
        cur.execute(
            f"""
            WITH tagged_plays AS (
                SELECT
                    yards_gained,
                    {normalized_type} AS play_type
                FROM plays
                WHERE game_name = %s
            )
            SELECT
                COUNT(*),
                COUNT(*) FILTER (
                    WHERE play_type IN ('Run', 'Pass')
                ),
                COALESCE(
                    SUM(yards_gained) FILTER (
                        WHERE play_type IN ('Run', 'Pass')
                    ), 0
                ),
                AVG(yards_gained) FILTER (
                    WHERE play_type IN ('Run', 'Pass')
                )
            FROM tagged_plays;
            """,
            (game_name,)
        )

        total_records, offensive_plays, total_yards, avg_yards = (
            cur.fetchone()
        )

        if total_records == 0:
            print(f"No plays found for {game_name}.")
            return

        # Distribution of play types.
        cur.execute(
            f"""
            SELECT
                {normalized_type} AS play_type,
                COUNT(*)
            FROM plays
            WHERE game_name = %s
            GROUP BY play_type
            ORDER BY COUNT(*) DESC, play_type;
            """,
            (game_name,)
        )

        play_types = cur.fetchall()

        # Down-by-down performance for runs and passes only.
        cur.execute(
            f"""
            SELECT
                down,
                COUNT(*),
                SUM(yards_gained),
                AVG(yards_gained)
            FROM plays
            WHERE game_name = %s
              AND {normalized_type} IN ('Run', 'Pass')
            GROUP BY down
            ORDER BY down;
            """,
            (game_name,)
        )

        down_stats = cur.fetchall()

        # Count plays with invalid/unrecorded field position.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM plays
            WHERE game_name = %s
              AND (yardline = 0 OR yardline IS NULL);
            """,
            (game_name,)
        )

        invalid_yardlines = cur.fetchone()[0]

        # Field-zone performance.
        #  -49 to -1 = own territory
        #  50 = midfield
        #  1 to 49 = opponent territory
        cur.execute(
            f"""
            SELECT
                CASE
                    WHEN yardline BETWEEN -49 AND -1
                        THEN 'Own territory'
                    WHEN yardline = 50
                        THEN 'Midfield'
                    WHEN yardline BETWEEN 1 AND 49
                        THEN 'Opponent territory'
                END AS field_zone,
                COUNT(*),
                SUM(yards_gained),
                AVG(yards_gained)
            FROM plays
            WHERE game_name = %s
              AND yardline BETWEEN -49 AND 50
              AND yardline <> 0
              AND {normalized_type} IN ('Run', 'Pass')
            GROUP BY field_zone
            ORDER BY MIN(yardline);
            """,
            (game_name,)
        )

        field_stats = cur.fetchall()

        # Display the report.
        print(f"\nGAME: {game_name}")
        print("-" * 60)
        print(f"Total charted records: {total_records}")
        print(f"Offensive run/pass plays: {offensive_plays}")
        print(f"Total yards on run/pass plays: {total_yards}")

        if avg_yards is None:
            print("Average yards per run/pass play: N/A")
        else:
            print(
                f"Average yards per run/pass play: "
                f"{avg_yards:.2f}"
            )

        print("\nPLAY TYPE DISTRIBUTION")
        print("-" * 40)

        for play_type, count in play_types:
            percentage = count / total_records * 100
            print(
                f"{play_type}: {count} records "
                f"({percentage:.1f}%)"
            )

        print("\nPERFORMANCE BY DOWN")
        print("-" * 60)
        print(
            f"{'Down':<10}{'Plays':<10}"
            f"{'Total Yds':<15}{'Avg Yds':<10}"
        )

        for down, count, total, average in down_stats:
            label = str(down) if down else "Unknown"
            avg_label = (
                f"{average:.2f}" if average is not None else "N/A"
            )
            print(
                f"{label:<10}{count:<10}"
                f"{total:<15}{avg_label:<10}"
            )

        print("\nPERFORMANCE BY FIELD ZONE")
        print("-" * 60)
        print(
            f"{'Zone':<25}{'Plays':<10}"
            f"{'Total Yds':<15}{'Avg Yds':<10}"
        )

        if not field_stats:
            print("No valid field-position data for run/pass plays.")
        else:
            for zone, count, total, average in field_stats:
                print(
                    f"{zone:<25}{count:<10}"
                    f"{total:<15}{average:.2f}"
                )

        print(
            f"\nRecords with invalid/unrecorded yardline: "
            f"{invalid_yardlines}"
        )

        print("\nReport complete.")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()