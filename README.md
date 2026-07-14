# PPE & Equipment Management System
## JSW Port Operations - Safety Department

---

## QUICK START (Windows)

1. Install Python from https://www.python.org/downloads/
   - During install, check ✅ "Add Python to PATH"

2. Double-click **START.bat**

3. Open browser: http://localhost:5000

---


## MODULES

### 📊 Dashboard
- KPI cards: Total employees, items, stock, issued today/month
- Low stock alerts
- Overdue return alerts
- PPE expiry alerts
- Calibration due alerts
- Charts: Top consumed items, monthly trend, department-wise

### 👷 Employee Master
- Add/Edit/Delete employees
- Fields: Employee Code, Name, Department, Contractor, Designation
- Status: Active/Inactive

### 🏭 Contractor Master
- Add/manage contractors
- Link contractors to employees

### 📦 Item Master
- PPE & Operational Equipment categories
- Min stock & reorder levels
- Expiry tracking flag
- Calibration tracking flag

### 🚚 Stock Receipt (GRN)
- Receive stock from stores
- GRN number tracking
- Auto updates inventory
- Receipt history

### 🤝 Issue PPE/Equipment
- Search employee by name or code
- Real-time stock availability check
- Returnable item tracking
- Return due date setting

### ↩️ Return Register
- View all pending returns
- Overdue returns highlighted in red
- Record condition on return (Good/Fair/Damaged/Scrapped)
- Auto restores stock

### 📚 Stock Ledger
- Item-wise transaction history
- Running balance
- Receipts vs Issues

### 🗓️ Expiry Tracking
- Track expiry dates for helmets, life jackets, respirators, etc.
- Alerts for items expiring within 30 days
- Dispose/scrap marking

### 🔧 Calibration Tracking
- Gas detectors, weighing equipment, measuring devices
- Calibration due date alerts
- Track calibration agency

### 📈 Reports & KPI
- Employee-wise issue history
- Department-wise consumption
- Contractor-wise consumption
- Item-wise consumption
- Monthly trend report
- Current stock status
- Export to Excel (xlsx)
- Print-friendly PDF view

---

## PORT-SPECIFIC ITEMS TO ADD

In Item Master, add these items for port operations:

**Life Safety:**
- Life Jacket (has_expiry = Yes)
- Safety Harness (has_expiry = Yes)
- Immersion Suit

**PPE:**
- Safety Helmet
- Safety Shoes
- Reflective Jacket
- Safety Gloves
- Safety Goggles
- Ear Muffs
- Dust Mask / Respirator (has_expiry = Yes)
- Face Shield

**Gas Detection:**
- Multi-Gas Detector (has_calibration = Yes)
- O2 Monitor (has_calibration = Yes)
- H2S Monitor (has_calibration = Yes)

**Operational Equipment:**
- Walkie-Talkie / Radio
- Safety Cone
- Barricade Tape
- Fire Extinguisher (has_expiry = Yes)
- Flashlight / Torch
- Lockout Tagout Kit

---

## FILE STRUCTURE

```
ppe_system/
├── app.py              ← Main application
├── START.bat           ← Double-click to run
├── requirements.txt    ← Python packages
├── database/
│   ├── db.py           ← Database setup
│   └── ppe_inventory.db ← SQLite database (auto-created)
├── modules/
│   ├── auth.py         ← Login/Logout
│   ├── dashboard.py    ← KPI Dashboard
│   ├── employees.py    ← Employee & Contractor management
│   ├── items.py        ← Item Master
│   ├── stock.py        ← Stock Receipt & Ledger
│   ├── issues.py       ← Issue PPE
│   ├── returns.py      ← Return Register
│   ├── expiry.py       ← Expiry Tracking
│   ├── calibration.py  ← Calibration Tracking
│   └── reports.py      ← Reports & Exports
└── templates/
    ├── base.html       ← Navigation & layout
    ├── login.html
    ├── dashboard.html
    ├── employees.html
    ├── contractors.html
    ├── items.html
    ├── stock.html
    ├── issues.html
    ├── returns.html
    ├── ledger.html
    ├── expiry.html
    ├── calibration.html
    ├── reports.html
    └── report_view.html
```

---

## BACKUP

The database is stored at: `database/ppe_inventory.db`

To backup: Copy this file to a USB or network drive regularly.

---

## AUDIT READINESS

This system supports:
- ✅ ISO 45001 / OHSAS 18001 PPE records
- ✅ IMS audit trails
- ✅ JSAP (JSW Safety Audit Program) reports
- ✅ Employee-wise PPE compliance history
- ✅ Contractor PPE tracking
- ✅ PPE expiry monitoring
- ✅ Gas detector calibration records
- ✅ Department-wise KPI reports

---

Developed for JSW Port Operations | Safety Department












<!-- mailer setup  -->
# What's included & how to wire it up

## Files
- `database/db.py` — adds `email` column to `users`, adds `password_reset_otp` table
- `utils/mailer.py` — SMTP email sender + OTP email template
- `modules/password_reset.py` — new Blueprint: forgot-password → verify OTP → set new password
- `modules/user_admin.py` — Add/Edit user now accept & save `email`
- `templates/users_admin.html` — Email column in the table + Email field in Add/Edit modals
- `templates/login.html` — adds a "Forgot password?" link
- `templates/forgot_password.html`, `verify_otp.html`, `reset_password.html` — new pages, styled to match your login page

## 1. Register the new blueprint
In your main `app.py`, alongside your other blueprint registrations:

```python
from modules.password_reset import password_reset_bp
app.register_blueprint(password_reset_bp)
```

## 2. Add SMTP settings to your `.env`
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM_NAME=PPE Management System
```
For Gmail you need an **App Password** (Google Account → Security → App
Passwords), not your normal login password. Any other provider (Office365,
company SMTP, SendGrid SMTP relay, etc.) works too — just change
`SMTP_HOST`/`SMTP_PORT`.

## 3. Update the database
Since `init_db()` uses `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT
EXISTS`, just re-run your existing `init_db()` once (e.g. restart the app
if it calls `init_db()` on startup, or run it manually) — existing data is
untouched, it only adds the new column/table.

## 4. Give users an email address
Existing users won't have an email until you (or they) add one — open
**User Management → Edit** for each user and fill in the Email field, or
have them added at creation time from now on going forward.

## Flow for the end user
1. Login page → **Forgot password?**
2. Enter username or email → OTP emailed (valid 10 minutes)
3. Enter the 6-digit OTP
4. Set a new password → redirected to login

## Security note
Your current codebase stores passwords in plain text (matching the existing
`users.password` column), so this reset flow does the same for consistency.
If you'd like, I can also switch everything over to hashed passwords
(`werkzeug.security.generate_password_hash` / `check_password_hash`) — happy
to do that as a follow-up change to your login route and this reset flow.


