import os
import psycopg2
from urllib.parse import urlparse

def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL no está definida en las variables de entorno.")

    result = urlparse(database_url)

    conn = psycopg2.connect(
        dbname=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        sslmode="require"  # Muy importante para Render
    )
    return conn
