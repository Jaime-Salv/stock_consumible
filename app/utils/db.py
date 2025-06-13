import os
import psycopg2
import time
from urllib.parse import urlparse

def get_connection(retries=10, delay=5):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL no está definida.")

    result = urlparse(database_url)

    for attempt in range(1, retries + 1):
        try:
            print(f"Intento {attempt}: conectando a la base de datos...")
            conn = psycopg2.connect(
                dbname=result.path[1:],
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port,
                sslmode="require"
            )
            print("✅ Conexión a la base de datos establecida.")
            return conn
        except psycopg2.OperationalError as e:
            print(f"❌ Error de conexión ({attempt}/{retries}): {e}")
            if attempt == retries:
                print("⛔ No se pudo establecer conexión con la base de datos después de varios intentos.")
                raise
            time.sleep(delay)

