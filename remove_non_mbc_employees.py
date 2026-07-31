"""
Keep only MBC / MANPOWER BASED category employees; remove everyone else.

WHAT THIS DOES
--------------
For every employee whose `category` is NOT 'MBC' and NOT 'MANPOWER BASED'
(this includes '', NULL, and any other value like 'STAFF', 'ASSOCIATE', etc.):

  1. If the employee has NO issue/return history (no rows referencing them
     in issue_register, contractor_issue_register, or return_register),
     they are HARD DELETED — same as the app's own "Delete" button:
     a tombstone row is written to `deleted_employees` first (so the next
     SQL Server sync never re-inserts them), then the employees row itself
     is removed.

  2. If the employee DOES have issue/return history, they CANNOT be hard
     deleted (the database's foreign key constraints forbid it, same as
     if you clicked "Delete" on them in the app — it would just error out).
     Instead, they are marked `status='Inactive'` so they stop appearing
     as active/issuable, while all history is preserved.

USAGE
-----
Preview only, no changes made:
    python remove_non_mbc_employees.py --dry-run

Actually apply the changes (asks for a final y/n confirmation first):
    python remove_non_mbc_employees.py

Skip the confirmation prompt (e.g. for scripted/unattended runs):
    python remove_non_mbc_employees.py --yes
"""

import sys
from database.db import get_db, fetchall, fetchone

VALID_CATEGORIES = {'MBC', 'MANPOWER BASED'}


def _has_history(cursor, employee_id):
    """True if this employee is referenced by any issue/return record."""
    cursor.execute("""
        SELECT
            EXISTS(SELECT 1 FROM issue_register WHERE employee_id=%s) OR
            EXISTS(SELECT 1 FROM contractor_issue_register WHERE employee_id=%s) OR
            EXISTS(SELECT 1 FROM return_register WHERE employee_id=%s)
            AS has_history
    """, (employee_id, employee_id, employee_id))
    row = fetchone(cursor)
    return bool(row and row['has_history'])


def run(dry_run=False, skip_confirm=False):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT id, emp_code, name, category, status
        FROM employees
        WHERE UPPER(COALESCE(category, '')) NOT IN %s
        ORDER BY name
    """, (tuple(VALID_CATEGORIES),))
    targets = fetchall(c)

    if not targets:
        print("Nothing to do — every employee already has category MBC or MANPOWER BASED.")
        conn.close()
        return

    to_delete = []
    to_deactivate = []
    for emp in targets:
        if _has_history(c, emp['id']):
            to_deactivate.append(emp)
        else:
            to_delete.append(emp)

    print(f"Found {len(targets)} employee(s) outside MBC / MANPOWER BASED:")
    print(f"  - {len(to_delete)} with no issue/return history -> will be DELETED")
    print(f"  - {len(to_deactivate)} with existing issue/return history -> will be marked INACTIVE")
    print()

    if dry_run:
        print("--- DRY RUN: no changes made ---")
        print()
        print("Would DELETE:")
        for e in to_delete:
            print(f"  {e['emp_code']} - {e['name']} (category: {e['category']!r})")
        print()
        print("Would mark INACTIVE (has history, cannot be deleted):")
        for e in to_deactivate:
            print(f"  {e['emp_code']} - {e['name']} (category: {e['category']!r}, current status: {e['status']})")
        conn.close()
        return

    if not skip_confirm:
        confirm = input(
            f"This will permanently delete {len(to_delete)} employee(s) and "
            f"deactivate {len(to_deactivate)} employee(s). Type 'yes' to proceed: "
        )
        if confirm.strip().lower() != 'yes':
            print("Aborted — no changes made.")
            conn.close()
            return

    deleted_count = 0
    deactivated_count = 0
    errors = []

    try:
        for emp in to_delete:
            try:
                c.execute("""
                    INSERT INTO deleted_employees (emp_code, name, deleted_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (emp_code) DO UPDATE
                        SET name=EXCLUDED.name, deleted_by=EXCLUDED.deleted_by, deleted_at=CURRENT_TIMESTAMP
                """, (emp['emp_code'], emp['name'], 'category_cleanup_script'))
                c.execute("DELETE FROM employees WHERE id=%s", (emp['id'],))
                conn.commit()
                deleted_count += 1
            except Exception as e:
                conn.rollback()
                errors.append(f"{emp['emp_code']} ({emp['name']}): delete failed — {e}")

        for emp in to_deactivate:
            try:
                c.execute("UPDATE employees SET status='Inactive' WHERE id=%s", (emp['id'],))
                conn.commit()
                deactivated_count += 1
            except Exception as e:
                conn.rollback()
                errors.append(f"{emp['emp_code']} ({emp['name']}): deactivate failed — {e}")

    finally:
        conn.close()

    print(f"Done. {deleted_count} deleted, {deactivated_count} marked Inactive.")
    if errors:
        print(f"\n{len(errors)} row(s) had errors:")
        for err in errors:
            print(f"  - {err}")


if __name__ == "__main__":
    dry_run = '--dry-run' in sys.argv
    skip_confirm = '--yes' in sys.argv
    run(dry_run=dry_run, skip_confirm=skip_confirm)