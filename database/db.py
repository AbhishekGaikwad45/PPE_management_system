import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host':     os.environ.get('PG_HOST'),
    'port':     os.environ.get('PG_PORT'),
    'database': os.environ.get('PG_DATABASE'),
    'user':     os.environ.get('PG_USER'),
    'password': os.environ.get('PG_PASSWORD'),
}


def get_database_url():
    from urllib.parse import quote_plus

    user = quote_plus(DB_CONFIG['user'])
    password = quote_plus(DB_CONFIG['password'])
    host = DB_CONFIG['host']
    port = DB_CONFIG['port']
    database = DB_CONFIG['database']
    return f'postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}'


def get_db():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn


def fetchall(cursor):
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def fetchone(cursor):
    if cursor.description is None:
        return None
    cols = [desc[0] for desc in cursor.description]
    row = cursor.fetchone()
    return dict(zip(cols, row)) if row else None
