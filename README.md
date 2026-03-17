# PocketFlow — Smart Expense Tracker

A full-stack web application built with **Python / Flask**, **SQLite**, **Bootstrap 5**, and **Chart.js** that lets individuals track personal expenses and provides administrators a platform-wide oversight dashboard.

---

## Features

### Module 1 — Expense Entry & Categorisation
| # | Feature |
|---|---------|
| 1 | View & update profile (username, email, password) |
| 2 | Add expenses with title, amount, date, and category |
| 3 | 8 predefined categories: Food, Transport, Entertainment, Bills, Shopping, Health, Education, Other |
| 4 | Custom notes & comma-separated tags per expense |

### Module 2 — Expense Tracking & Management
| # | Feature |
|---|---------|
| 1 | Edit existing expense entries |
| 2 | Delete unwanted expense records |
| 3 | View all expenses in an organised, sortable table on the dashboard |
| 4 | Filter/search by date range, category, min/max amount, and keyword |

### Module 3 — Analytics & Admin Oversight
| # | Feature |
|---|---------|
| 1 | Total spending, entry count, monthly total, and average displayed on dashboard |
| 2 | Admins can view, edit, or delete **any** user's expense entries |
| 3 | Doughnut chart (category breakdown) + Bar chart (monthly trend) |
| 4 | Admin dashboard with per-user expense summaries and platform-wide stats |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Backend | Flask 3.0 |
| Database | SQLite (built-in) |
| Frontend | HTML5, Bootstrap 5.3, Bootstrap Icons |
| Charts | Chart.js 4.4 |
| Deployment | PythonAnywhere |

---

## Project Structure

```
PocketFlow/
├── app.py                  # Flask application & all routes
├── pocket_flow.db          # SQLite database (auto-created on first run)
├── requirements.txt
├── static/
│   ├── css/style.css       # Custom styles
│   └── js/main.js          # Chart helpers & delete confirmation
└── templates/
    ├── base.html           # Shared layout (navbar, flash messages, footer)
    ├── index.html          # Public landing page
    ├── profile.html        # User profile update
    ├── auth/
    │   ├── login.html
    │   └── register.html
    ├── expenses/
    │   ├── dashboard.html  # User dashboard (table + charts + filters)
    │   ├── add_expense.html
    │   └── edit_expense.html
    └── admin/
        ├── dashboard.html       # Admin overview (all users + charts)
        ├── user_expenses.html   # Admin view of one user's expenses
        └── edit_expense.html    # Admin edit any expense
```

---

## Local Setup

```bash
# 1. Clone / download the project
cd "Pocket Flow"

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app (database is auto-created)
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## Default Credentials

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `Admin@123` |
| Regular user | register a new account | — |

> **Security note:** Change the admin password and set a strong `SECRET_KEY` environment variable before deploying to production.

---

## PythonAnywhere Deployment

1. Upload project files to PythonAnywhere (via Git or ZIP upload).
2. Create a new Web App → Manual configuration → Python 3.10.
3. Set the **WSGI file** to point to your `app.py`:
   ```python
   import sys
   sys.path.insert(0, '/home/<username>/Pocket Flow')
   from app import app as application
   application.secret_key = 'your-production-secret-key'
   ```
4. Set the **static files** mapping: `/static/` → `/home/<username>/Pocket Flow/static`.
5. Reload the web app.

---

## Future Work (Planned)
- Monthly / yearly reports with PDF or Excel export
- Budget-setting with spending-limit alerts
- Receipt image upload for expense verification
# PocketFlow
