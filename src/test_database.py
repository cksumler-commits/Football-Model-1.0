import psycopg

connection = psycopg.connect(
    "dbname=Football-Model1.0 user=postgres password=J-brown2026 host=localhost port=5432"
)

print("Database connection successful!")

connection.close()