import psycopg


conn = psycopg.connect(
    dbname="Football-Model1.0",
    user="postgres",
    password="J-brown2026",
    host="localhost",
    port="5432"
)

cur = conn.cursor()

game_name = input("Enter Game Name: ")

cur.execute(
    """
    SELECT
        play_number,
        quarter,
        game_time,
        down,
        distance,
        hash,
        rpn,
        yards_gained,
        result_reason
    FROM plays
    WHERE game_name = %s
    ORDER BY play_number;
    """,
    (game_name,)
)

plays = cur.fetchall()

print()
print(f"GAME: {game_name}")
print("-" * 80)

if len(plays) == 0:
    print("No plays found.")

else:
    for play in plays:
        print(
            f"Play {play[0]} | "
            f"Q{play[1]} | "
            f"{play[2]} | "
            f"{play[3]} & {play[4]} | "
            f"{play[5]} | "
            f"{play[6]} | "
            f"Yards: {play[7]} | "
            f"{play[8]}"
        )

cur.close()
conn.close()