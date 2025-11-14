# db.py (Postgres version)
import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", 5432))
PG_DB = os.getenv("PG_DB", "yourdb")
PG_USER = os.getenv("PG_USER", "youruser")
PG_PASS = os.getenv("PG_PASSWORD", "")

def _translate_oracle_sql(q):
    """
    Do simple translations from common Oracle constructs to Postgres:
    - replace :1, :2, ... with %s
    - NVL -> COALESCE
    - SYSTIMESTAMP -> NOW()
    - SYSDATE -> CURRENT_DATE
    (This is a pragmatic layer; complex queries may still need manual edits.)
    """
    # replace :1, :2 etc with %s
    q = re.sub(r":\d+", "%s", q)
    # common function name replacements
    q = q.replace("NVL(", "COALESCE(")
    q = q.replace("SYSTIMESTAMP", "NOW()")
    q = q.replace("SYSDATE", "CURRENT_DATE")
    # TRUNC(date) used in Oracle to remove time-of-day -> convert to DATE(...) in many contexts
    q = q.replace("TRUNC(", "DATE(")  # careful: may need manual checks for complex uses
    return q

def get_conn():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASS
    )

def execute_query(query, params=None, fetch=False, returning=False):
    """
    Execute a SQL query with params.
    - query: may contain Oracle-style placeholders (:1, :2); they will be converted.
    - params: tuple/list of parameters in same order as placeholders.
    - fetch: if True, returns a list of tuples from cursor.fetchall()
    - returning: if True, expects an INSERT ... RETURNING id and returns cursor.fetchone()[0]
    """
    q = _translate_oracle_sql(query)
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        if params:
            cur.execute(q, params)
        else:
            cur.execute(q)

        if returning:
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return row[0] if row else None

        data = None
        if fetch:
            data = cur.fetchall()
        conn.commit()
        cur.close()
        return data
    except Exception as e:
        if conn:
            conn.rollback()
        print("DB error:", e)
        raise
    finally:
        if conn:
            conn.close()
