import psycopg


def get_connection():
    # Keep the connection settings that already work on your computer.
    return psycopg.connect(
        dbname="Football-Model1.0",
        user="postgres",
        password="J-brown2026",
        host="localhost",
        port="5432"
    )


def get_integer(prompt, current_value, minimum=None, maximum=None):
    """Blank keeps the current value; invalid numbers are rejected."""

    while True:
        value = input(
            f"{prompt} [{current_value}]: "
        ).strip()

        if not value:
            return current_value

        try:
            number = int(value)
        except ValueError:
            print("Enter a whole number, or press Enter to keep the current value.")
            continue

        if minimum is not None and number < minimum:
            print(f"Value must be at least {minimum}.")
            continue

        if maximum is not None and number > maximum:
            print(f"Value must be no greater than {maximum}.")
            continue

        return number


def get_text(prompt, current_value):
    """Blank keeps the current text value."""

    value = input(f"{prompt} [{current_value}]: ").strip()

    if not value:
        return current_value

    return value


def main():
    conn = get_connection()
    cur = conn.cursor()

    try:
        print("EDIT PLAY")
        print("-" * 60)

        game_name = input("Enter the game name: ").strip()

        if not game_name:
            print("Game name cannot be blank.")
            return

        cur.execute(
            """
            SELECT
                id,
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
                hash_mark,
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
                f"Hash: {hash_mark} | "
                f"{rpn} | "
                f"Yardline: {yardline} | "
                f"Yards: {yards_gained} | "
                f"Reason: {result_reason}"
            )

        print("\nEnter the database ID of the play you want to edit.")
        selection = input("Record ID (or Q to quit): ").strip()

        if selection.upper() == "Q":
            return

        try:
            record_id = int(selection)
        except ValueError:
            print("Record ID must be a whole number.")
            return

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
            WHERE id = %s AND game_name = %s;
            """,
            (record_id, game_name)
        )

        play = cur.fetchone()

        if play is None:
            print("That record ID was not found in this game.")
            return

        (
            record_id,
            old_game_name,
            old_series,
            old_play_number,
            old_quarter,
            old_time,
            old_down,
            old_distance,
            old_hash,
            old_rpn,
            old_yardline,
            old_yards,
            old_reason
        ) = play

        print("\nEnter a new value to change a field.")
        print("Press Enter to keep its current value.")
        print("-" * 60)

        new_game_name = get_text("Game Name", old_game_name)

        new_series = get_integer("Series Number", old_series, minimum=0)
        new_play_number = get_integer("Play Number", old_play_number, minimum=0)
        new_quarter = get_integer("Quarter", old_quarter, minimum=0)
        new_time = get_text("Time (MM:SS)", old_time)
        new_down = get_integer("Down", old_down, minimum=0)
        new_distance = get_integer("Distance", old_distance, minimum=0)
        new_hash = get_text("Hash", old_hash)
        new_rpn = get_text("R/P/N", old_rpn)

        new_yardline = get_integer(
            "Yardline (-49 to 50)",
            old_yardline,
            minimum=-49,
            maximum=50
        )

        new_yards = get_integer("Yards Gained", old_yards)
        new_reason = get_text("Result Reason", old_reason)

        print("\nReview your changes:")
        print(f"Game: {old_game_name} -> {new_game_name}")
        print(f"Series: {old_series} -> {new_series}")
        print(f"Play: {old_play_number} -> {new_play_number}")
        print(f"Yardline: {old_yardline} -> {new_yardline}")
        print(f"Yards gained: {old_yards} -> {new_yards}")
        print(f"Result reason: {old_reason} -> {new_reason}")

        confirm = input("\nSave these changes? (Y/N): ").strip().upper()

        if confirm != "Y":
            print("Changes cancelled. Nothing was updated.")
            return

        cur.execute(
            """
            UPDATE plays
            SET
                game_name = %s,
                series_number = %s,
                play_number = %s,
                quarter = %s,
                game_time = %s,
                down = %s,
                distance = %s,
                hash = %s,
                rpn = %s,
                yardline = %s,
                yards_gained = %s,
                result_reason = %s
            WHERE id = %s;
            """,
            (
                new_game_name,
                new_series,
                new_play_number,
                new_quarter,
                new_time,
                new_down,
                new_distance,
                new_hash,
                new_rpn,
                new_yardline,
                new_yards,
                new_reason,
                record_id
            )
        )

        conn.commit()
        print("\nPlay updated successfully.")

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()