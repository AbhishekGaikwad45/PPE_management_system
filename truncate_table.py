from database.db import get_db

def truncate_deleted_employees():
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM deleted_employees")
        before = cur.fetchone()[0]

        print(f"Records before truncate: {before}")

        cur.execute("TRUNCATE TABLE deleted_employees RESTART IDENTITY")

        conn.commit()

        cur.execute("SELECT COUNT(*) FROM deleted_employees")
        after = cur.fetchone()[0]

        print(f"Records after truncate: {after}")
        print("deleted_employees table truncated successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    truncate_deleted_employees()