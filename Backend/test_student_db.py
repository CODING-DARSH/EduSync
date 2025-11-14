import psycopg2

print("\n=== FINAL DB CHECK ===\n")

try:
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="student_management",   # your new DB
        user="postgres",
        password="Darsh"
    )

    print("✔ Connected to student_management\n")
    cur = conn.cursor()

    # 1. Check tables
    print("📌 Tables in public schema:")
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema='public';
    """)
    for row in cur.fetchall():
        print(" -", row[0])

    # 2. Select sample data from students (if exists)
    print("\n📌 Checking students table:")
    try:
        cur.execute("SELECT * FROM Students;")
        data = cur.fetchall()
        if not data:
            print("(empty table)")
        else:
            for row in data:
                print(row)
    except Exception as e:
        print("⚠ Cannot fetch from students:", e)

    cur.close()
    conn.close()

except Exception as e:
    print("❌ ERROR:", e)
