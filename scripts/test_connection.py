
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

try:
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

    print("Python connected to PostgreSQL successfully!")

    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    print(cursor.fetchone()[0])

    cursor.close()
    conn.close()

except Exception as e:
    print("Connection failed:", e)
