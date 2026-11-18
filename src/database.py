import psycopg


def get_connection():
    # Use the same connection settings as your working game_summary.py.
    return psycopg.connect(
        dbname="Football-Model1.0",
        user="postgres",
        password="J-brown2026",
        host="localhost",
        port="5432",
    )




    