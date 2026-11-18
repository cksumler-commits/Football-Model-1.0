
import psycopg


def get_connection():
    return psycopg.connect(
        dbname="Football-Model1.0",
        user="postgres",
        password="J-brown2026",
        host="localhost",
        port="5432"
    )


def get_integer(prompt, default=None, minimum=None, maximum=None):
    """Accept whole numbers and safely handle invalid input."""

    while True:
        value = input(prompt).strip()

        if value == "" and default is not None:
            return default

        try:
            number = int(value)
        except ValueError:
            print("Enter a valid whole number.")
            continue

        if minimum is not None and number < minimum:
            print(f"Enter a number of at least {minimum}.")
            continue

        if maximum is not None and number > maximum:
            print(f"Enter a number no greater than {maximum}.")
            continue

        return number


def get_text(prompt):
    """Use N/A when a text field is left blank."""

    value = input(prompt).strip()
    return value if value else "N/A"


def main():
    conn = get_connection()
    cur = conn.cursor()

    try:
        print("FOOTBALL INTELLIGENCE PLATFORM")
        print("=" * 40)

        game_name = input("Game Name: ").strip()

        if not game_name:
            game_name = "N/A"

        # Find the next play number for this game.
        cur.execute(
            """
            SELECT COALESCE(MAX(play_number), 0)
            FROM plays
            WHERE game_name = %s;
            """,
            (game_name,)
        )

        last_play_number = cur.fetchone()[0]
        first_play_number = last_play_number + 1

        if last_play_number > 0:
            print(f"\nExisting game found: {game_name}")
            print(f"Last recorded play: {last_play_number}")
            print(f"Next play number: {first_play_number}")
        else:
            print(f"\nStarting a new game chart: {game_name}")
            first_play_number = 1

        number_of_plays = get_integer(
            "How many plays do you want to enter? ",
            minimum=1
        )

        print("\nBlank text fields become N/A.")
        print("Blank integer fields become 0.")
        print("Yardline must be between -49 and 50.")
        print("=" * 40)

        for play_number in range(
            first_play_number,
            first_play_number + number_of_plays
        ):
            print(f"\nPLAY {play_number}")
            print("-" * 30)

            series_number = get_integer(
                "Series Number: ", default=0, minimum=0
            )

            quarter = get_integer(
                "Quarter: ", default=0, minimum=0, maximum=4
            )

            game_time = get_text("Time (MM:SS): ")

            down = get_integer(
                "Down: ", default=0, minimum=0, maximum=4
            )

            distance = get_integer(
                "Distance: ", default=0, minimum=0
            )

            hash_mark = get_text("Hash (Left/Middle/Right): ")

            rpn = get_text("R/P/N: ")

            yardline = get_integer(
                "Yardline (-49 to 50): ",
                default=0,
                minimum=-49,
                maximum=50
            )

            yards_gained = get_integer(
                "Yards Gained: ", default=0
            )

            result_reason = get_text("Result Reason: ")

            cur.execute(
                """
                INSERT INTO plays (
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
                )
                VALUES (%s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s);
                """,
                (
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
                )
            )

            # Save this play immediately.
            conn.commit()

            print(f"Play {play_number} saved successfully.")

            if play_number < first_play_number + number_of_plays - 1:
                continue_charting = input(
                    "Continue to next play? (Y/N): "
                ).strip().upper()

                if continue_charting == "N":
                    print("Charting stopped. Saved plays are preserved.")
                    break

        print("\n" + "=" * 40)
        print(f"Charting session complete: {game_name}")
        print("All saved plays are preserved.")

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()