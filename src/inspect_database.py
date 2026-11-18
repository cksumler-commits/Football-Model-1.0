from database import get_connection

try:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    table_name,
                    column_name,
                    data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """)

            rows = cur.fetchall()

            current_table = None

            for table, column, data_type in rows:
                if table != current_table:
                    current_table = table
                    print(f"\n--- {table} ---")

                print(f"  {column}: {data_type}")

except Exception as error:
    print(f"Database inspection failed: {error}")