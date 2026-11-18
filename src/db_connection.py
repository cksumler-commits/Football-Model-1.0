import psycopg

try:
    conn = psycopg.connect(
        dbname="Football-Model1.0",
        user="postgres",
        password="J-brown2026",
        host="localhost",
        port="5432"
    )

    print("Connected successfully!")

    conn.close()

except Exception as e:
    print("Connection failed:")
    print(e)