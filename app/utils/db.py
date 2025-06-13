import os
import psycopg2
import time
from urllib.parse import urlparse

def get_connection(retries=5, delay=3):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL no está definida.")

    result = urlparse(database_url)

    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(
                dbname=result.path[1:],
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port,
                sslmode="require"
            )
            return conn
        except psycopg2.OperationalError as e:
            if attempt == retries:
                raise
            time.sleep(delay)
