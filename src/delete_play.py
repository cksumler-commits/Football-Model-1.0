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
        print("DELETE PLAY")
        print("=" * 60)

        game_name = input("Enter Game Name: ").strip()

        if not game_name:
            print("Game name cannot be blank.")
            return

        # Retrieve the game's plays.
        cur.execute(
            """
            SELECT
                id,
                play_number,
                quarter,
                game_time,
                down,
                distance,
                rpn,
                yardline,
                yards_gained,
                result_reason
            FROM plays
            WHERE game_name = %s
            ORDER BY play_number, id;
            """,
            (game_name,)
        )

        plays = cur.fetchall()

        if not plays:
            print(f"No plays found for {game_name}.")
            return

        print(f"\nGAME: {game_name}")
        print("-" * 90)

        for play in plays:
            (
                record_id,
                play_number,
                quarter,
                game_time,
                down,
                distance,
                rpn,
                yardline,
                yards_gained,
                result_reason
            ) = play

            print(
                f"ID: {record_id} | "
                f"Play: {play_number} | "
                f"Q{quarter} {game_time} | "
                f"{down}&{distance} | "
                f"{rpn} | "
                f"Yardline: {yardline} | "
                f"Yards: {yards_gained} | "
                f"{result_reason}"
            )

        # Select by unique database ID, not play number.
        selection = input(
            "\nEnter the database ID to delete (or Q to quit): "
        ).strip()

        if selection.upper() == "Q":
            print("Deletion cancelled.")
            return

        try:
            record_id = int(selection)
        except ValueError:
            print("Record ID must be a whole number.")
            return

        # Verify the selected record belongs to this game.
        cur.execute(
            """
            SELECT
                id,
                play_number,
                quarter,
                game_time,
                down,
                distance,
                rpn,
                yardline,
                yards_gained,
                result_reason
            FROM plays
            WHERE id = %s AND game_name = %s;
            """,
            (record_id, game_name)
        )

        play = cur.fetchone()

        if play is None:
            print("That record ID was not found in this game.")
            return

        print("\nPLAY SELECTED FOR DELETION")
        print("-" * 60)
        print(f"Database ID: {play[0]}")
        print(f"Play Number: {play[1]}")
        print(f"Quarter / Time: Q{play[2]} / {play[3]}")
        print(f"Down & Distance: {play[4]} & {play[5]}")
        print(f"R/P/N: {play[6]}")
        print(f"Yardline: {play[7]}")
        print(f"Yards Gained: {play[8]}")
        print(f"Result Reason: {play[9]}")

        confirm = input(
            "\nPermanently delete this play? Type DELETE to confirm: "
        ).strip()

        if confirm != "DELETE":
            print("Deletion cancelled. The play was preserved.")
            return

        cur.execute(
            """
            DELETE FROM plays
            WHERE id = %s AND game_name = %s;
            """,
            (record_id, game_name)
        )

        if cur.rowcount == 1:
            conn.commit()
            print("Play deleted successfully.")
        else:
            conn.rollback()
            print("No play was deleted. Please verify the record.")

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()