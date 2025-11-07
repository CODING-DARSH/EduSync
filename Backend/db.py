import cx_Oracle

def get_connection():
    try:
        dsn = cx_Oracle.makedsn("localhost", 1521, service_name="XE")


        conn = cx_Oracle.connect(
            user="SCOTT",
            password="TIGER",
            dsn=dsn
        )
        print("Connected to Oracle successfully")
        return conn

    except cx_Oracle.DatabaseError as e:
        error, = e.args
        print(" Oracle connection failed")
        print(f"Code: {error.code}")
        print(f"Message: {error.message}")
        raise

def execute_query(query, params=None, fetch=False):
    conn = get_connection()
    cur = conn.cursor()

    if params:
        cur.execute(query, params)
    else:
        cur.execute(query)

    data = cur.fetchall() if fetch else None
    conn.commit()

    cur.close()
    conn.close()
    return data
