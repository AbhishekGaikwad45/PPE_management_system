import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()

SQL_CONFIG = {
    'driver':   os.environ.get('MSSQL_DRIVER',   'SQL Server'),
    'server':   os.environ.get('MSSQL_SERVER',   '172.21.30.101'),
    'database': os.environ.get('MSSQL_DATABASE', 'JSW_Dharamtar'),
    'uid':      os.environ.get('MSSQL_UID',      'Report'),
    'pwd':      os.environ.get('MSSQL_PWD',      ''),
}


def get_sql_connection():
    """
    Opens a NEW connection every call (do not cache/reuse a single global
    connection across requests in a web app).
    """
    driver = SQL_CONFIG['driver']
    pwd = SQL_CONFIG['pwd'].strip().strip('"').strip("'")  # guard against stray quotes/spaces in .env

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={SQL_CONFIG['server']};"
        f"DATABASE={SQL_CONFIG['database']};"
        f"UID={SQL_CONFIG['uid']};"
        f"PWD={pwd};"
    )

    # The legacy 'SQL Server' driver does NOT understand TrustServerCertificate
    # and throws "Invalid connection string attribute" if you send it.
    # Only the modern 'ODBC Driver 17/18 for SQL Server' drivers support it.
    if 'ODBC Driver' in driver:
        conn_str += "TrustServerCertificate=yes;"

    return pyodbc.connect(conn_str, timeout=10)


def sql_fetchall(cursor):
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]