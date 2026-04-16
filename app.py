from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
import sqlite3
import hashlib
import os
import secrets
import time
import calendar
from collections import defaultdict
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'pocket-flow-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB limit

DATABASE = 'pocket_flow.db'
CATEGORIES = ['Food', 'Transport', 'Entertainment', 'Bills', 'Shopping', 'Health', 'Education', 'Other']
UPLOAD_FOLDER   = os.path.join('static', 'uploads', 'avatars')
ALLOWED_EXT     = {'jpg', 'jpeg', 'png', 'gif', 'webp'}


# ── Database helpers ───────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def is_valid_image(stream):
    """Validate file is a real image by checking magic bytes."""
    header = stream.read(512)
    stream.seek(0)
    if header[:3] == b'\xff\xd8\xff':              return True  # JPEG
    if header[:8] == b'\x89PNG\r\n\x1a\n':        return True  # PNG
    if header[:6] in (b'GIF87a', b'GIF89a'):       return True  # GIF
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP': return True  # WEBP
    return False


def classify_risk(increase_pct):
    if increase_pct > 30:
        return 'High'
    if increase_pct >= 15:
        return 'Medium'
    return 'Low'


def _pct_change(current, baseline):
    if baseline <= 0:
        return None
    return ((current - baseline) / baseline) * 100


def build_spending_alerts(conn, user_id, monthly_budget=0.0):
    """Rule-based spending alerts for user dashboard (SQLite-safe, no ML)."""
    today = datetime.now().date()
    baseline_start = today - timedelta(days=7)
    week_start = today - timedelta(days=today.weekday())
    current_month_start = today.replace(day=1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)

    rows = conn.execute(
        'SELECT amount, category, date FROM expenses WHERE user_id = ? AND date >= ? ORDER BY date ASC',
        [user_id, (today - timedelta(days=95)).isoformat()]
    ).fetchall()

    baseline_cat = defaultdict(float)
    day_totals = defaultdict(float)
    week_cat = defaultdict(float)
    current_month_cat = defaultdict(float)
    prev_month_cat = defaultdict(float)

    baseline_total = 0.0
    current_month_total = 0.0
    prev_month_total = 0.0

    for r in rows:
        raw_date = r['date']
        try:
            expense_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            continue

        amount = float(r['amount'] or 0)
        if amount <= 0:
            continue
        category = r['category'] if r['category'] else 'Other'

        if baseline_start <= expense_date <= today:
            baseline_cat[category] += amount
            baseline_total += amount
            day_totals[expense_date] += amount

        if week_start <= expense_date <= today:
            week_cat[category] += amount

        if current_month_start <= expense_date <= today:
            current_month_cat[category] += amount
            current_month_total += amount

        if prev_month_start <= expense_date <= prev_month_end:
            prev_month_cat[category] += amount
            prev_month_total += amount

    alerts = []
    risk_counts = {'Low': 0, 'Medium': 0, 'High': 0}

    # Day-to-day increase checks inside rolling 7-day window (no need to wait 7 full days).
    ordered_days = sorted(day_totals.keys())
    for i in range(1, len(ordered_days)):
        prev_day = ordered_days[i - 1]
        curr_day = ordered_days[i]
        prev_total = day_totals.get(prev_day, 0.0)
        curr_total = day_totals.get(curr_day, 0.0)
        if prev_total <= 0 or curr_total <= prev_total:
            continue

        increase_pct = _pct_change(curr_total, prev_total)
        if increase_pct is None or increase_pct < 15:
            continue

        risk = classify_risk(increase_pct)
        alerts.append({
            'risk': risk,
            'kind': 'daily_increase',
            'category': 'Overall',
            'increase_pct': round(increase_pct, 1),
            'message': f"{curr_day.strftime('%A')} spending is {increase_pct:.1f}% higher than {prev_day.strftime('%A')}."
        })
        risk_counts[risk] += 1

    # Current week vs usual weekly average by category.
    weekly_baseline_factor = 7.0 / 7.0
    for category in sorted(set(list(baseline_cat.keys()) + list(week_cat.keys()))):
        baseline_weekly_avg = baseline_cat.get(category, 0.0) / weekly_baseline_factor
        current_week = week_cat.get(category, 0.0)
        if baseline_weekly_avg <= 0 or current_week <= baseline_weekly_avg:
            continue

        increase_pct = _pct_change(current_week, baseline_weekly_avg)
        if increase_pct is None or increase_pct < 15:
            continue

        risk = classify_risk(increase_pct)
        alerts.append({
            'risk': risk,
            'kind': 'weekly_category',
            'category': category,
            'increase_pct': round(increase_pct, 1),
            'message': f'{category} spending is {increase_pct:.1f}% higher than your usual weekly average.'
        })
        risk_counts[risk] += 1

    # Current month vs previous month by category.
    for category in sorted(set(list(current_month_cat.keys()) + list(prev_month_cat.keys()))):
        prev_amount = prev_month_cat.get(category, 0.0)
        curr_amount = current_month_cat.get(category, 0.0)
        if prev_amount <= 0 or curr_amount <= prev_amount:
            continue

        increase_pct = _pct_change(curr_amount, prev_amount)
        if increase_pct is None or increase_pct < 15:
            continue

        risk = classify_risk(increase_pct)
        alerts.append({
            'risk': risk,
            'kind': 'monthly_category',
            'category': category,
            'increase_pct': round(increase_pct, 1),
            'message': f'{category} spending is rising faster than last month ({increase_pct:.1f}% increase).'
        })
        risk_counts[risk] += 1

    # Month-end overspend projection against usual monthly baseline.
    elapsed_days = today.day
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if elapsed_days >= 3 and current_month_total > 0 and baseline_total > 0:
        projected_month_total = (current_month_total / elapsed_days) * days_in_month
        increase_pct = _pct_change(projected_month_total, baseline_total)
        if increase_pct is not None and increase_pct >= 15:
            risk = classify_risk(increase_pct)
            alerts.append({
                'risk': risk,
                'kind': 'monthly_projection',
                'category': 'Overall',
                'increase_pct': round(increase_pct, 1),
                'message': 'You may exceed your usual monthly spending soon.'
            })
            risk_counts[risk] += 1

    # Budget-crossing alert for user-defined monthly amount.
    try:
        monthly_budget = float(monthly_budget or 0)
    except (TypeError, ValueError):
        monthly_budget = 0.0

    if monthly_budget > 0 and current_month_total > monthly_budget:
        increase_pct = _pct_change(current_month_total, monthly_budget)
        increase_pct = increase_pct if increase_pct is not None else 0.0
        risk = classify_risk(increase_pct)
        alerts.append({
            'risk': risk,
            'kind': 'monthly_budget_crossed',
            'category': 'Budget',
            'increase_pct': round(increase_pct, 1),
            'message': f'You crossed your monthly budget (${monthly_budget:.2f}).'
        })
        risk_counts[risk] += 1

    # Keep alert list concise and most important first.
    alerts = sorted(alerts, key=lambda a: a['increase_pct'], reverse=True)[:6]

    top_risk = 'Low'
    if any(a['risk'] == 'High' for a in alerts):
        top_risk = 'High'
    elif any(a['risk'] == 'Medium' for a in alerts):
        top_risk = 'Medium'

    risk_score = {'Low': 30, 'Medium': 65, 'High': 90}[top_risk]

    has_enough_history = baseline_total > 0

    return {
        'risk_level': top_risk,
        'risk_score': risk_score,
        'alerts': alerts,
        'risk_counts': risk_counts,
        'has_enough_history': has_enough_history,
        'fallback_message': 'No spending found in the last 7 days.'
    }


def init_db():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            is_admin      INTEGER NOT NULL DEFAULT 0,
            avatar        TEXT    NOT NULL DEFAULT '',
            monthly_budget REAL   NOT NULL DEFAULT 0,
            remember_token TEXT NOT NULL DEFAULT '',
            remember_token_expiry INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            title      TEXT    NOT NULL,
            amount     REAL    NOT NULL,
            date       TEXT    NOT NULL,
            category   TEXT    NOT NULL,
            notes      TEXT    NOT NULL DEFAULT '',
            tags       TEXT    NOT NULL DEFAULT '',
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    ''')
    # Migration: add avatar column to existing databases
    try:
        conn.execute("ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute('ALTER TABLE users ADD COLUMN monthly_budget REAL NOT NULL DEFAULT 0')
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE users ADD COLUMN remember_token TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE users ADD COLUMN remember_token_expiry INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # columns already exist

    # Create default admin if none exists
    admin = conn.execute('SELECT id FROM users WHERE is_admin = 1').fetchone()
    if not admin:
        conn.execute(
            'INSERT INTO users (username, email, password_hash, is_admin) VALUES (?, ?, ?, ?)',
            ('admin', 'admin@pocketflow.com', hash_password('Admin@123'), 1)
        )
        conn.commit()
    conn.close()


# ── Auth decorators ────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        if not session.get('is_admin'):
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


@app.before_request
def load_user_from_remember_token():
    if 'user_id' in session:
        return
    token = request.cookies.get('remember_token')
    if not token:
        return

    conn = get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE remember_token = ? AND remember_token_expiry >= ?',
        (token, int(time.time()))
    ).fetchone()
    conn.close()
    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_admin'] = bool(user['is_admin'])
        session['avatar'] = user['avatar'] if user['avatar'] else ''


# ── Public routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('admin_dashboard') if session.get('is_admin') else url_for('dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')

        errors = []
        if len(username) < 3:
            errors.append('Username must be at least 3 characters.')
        if '@' not in email or '.' not in email:
            errors.append('A valid email address is required.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')

        if not errors:
            try:
                conn = get_db()
                conn.execute(
                    'INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                    (username, email, hash_password(password))
                )
                conn.commit()
                conn.close()
                flash('Account created! You can now log in.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                conn.close()
                errors.append('That username or email is already taken.')

        for err in errors:
            flash(err, 'danger')

    return render_template('auth/register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        conn = get_db()
        user = conn.execute(
            'SELECT * FROM users WHERE username = ? AND password_hash = ?',
            (username, hash_password(password))
        ).fetchone()

        if user:
            session.clear()
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['is_admin'] = bool(user['is_admin'])
            session['avatar']   = user['avatar'] if user['avatar'] else ''

            response = redirect(url_for('admin_dashboard') if user['is_admin'] else url_for('dashboard'))
            if remember:
                token = secrets.token_urlsafe(32)
                expiry = int(time.time()) + 30 * 24 * 60 * 60
                conn.execute(
                    'UPDATE users SET remember_token = ?, remember_token_expiry = ? WHERE id = ?',
                    (token, expiry, user['id'])
                )
                response.set_cookie('remember_token', token, max_age=30*24*60*60, httponly=True)
            else:
                conn.execute(
                    'UPDATE users SET remember_token = ?, remember_token_expiry = ? WHERE id = ?',
                    ('', 0, user['id'])
                )
                response.delete_cookie('remember_token')

            conn.commit()
            conn.close()
            flash(f'Welcome back, {user["username"]}!', 'success')
            return response

        conn.close()
        flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html')


@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        conn = get_db()
        conn.execute('UPDATE users SET remember_token = ?, remember_token_expiry = ? WHERE id = ?', ('', 0, user_id))
        conn.commit()
        conn.close()

    session.clear()
    response = redirect(url_for('index'))
    response.delete_cookie('remember_token')
    flash('You have been logged out.', 'info')
    return response


# ── Profile ────────────────────────────────────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_id = session['user_id']

    if request.method == 'POST':
        action           = request.form.get('action', 'update')
        username         = request.form.get('username', '').strip()
        email            = request.form.get('email', '').strip().lower()
        current_password = request.form.get('current_password', '')
        new_password     = request.form.get('new_password', '')

        # ── Remove avatar action ──────────────────────────────────────────────
        if action == 'remove_avatar':
            conn = get_db()
            row = conn.execute('SELECT avatar FROM users WHERE id = ?', [user_id]).fetchone()
            if row and row['avatar']:
                old_path = os.path.join('static', row['avatar'].lstrip('/'))
                if os.path.exists(old_path):
                    os.remove(old_path)
            conn.execute("UPDATE users SET avatar = '' WHERE id = ?", [user_id])
            conn.commit()
            conn.close()
            session['avatar'] = ''
            flash('Profile picture removed.', 'success')
            return redirect(url_for('profile'))

        errors = []
        if len(username) < 3:
            errors.append('Username must be at least 3 characters.')
        if '@' not in email or '.' not in email:
            errors.append('A valid email address is required.')

        conn = get_db()
        pwd_ok = conn.execute(
            'SELECT id FROM users WHERE id = ? AND password_hash = ?',
            [user_id, hash_password(current_password)]
        ).fetchone()
        conn.close()

        if not pwd_ok:
            errors.append('Current password is incorrect.')
        if new_password and len(new_password) < 6:
            errors.append('New password must be at least 6 characters.')

        # ── Avatar file upload ────────────────────────────────────────────────
        new_avatar_rel = None
        avatar_file = request.files.get('avatar')
        if avatar_file and avatar_file.filename:
            if not allowed_file(avatar_file.filename):
                errors.append('Only JPG, PNG, GIF, and WEBP images are allowed.')
            elif not is_valid_image(avatar_file.stream):
                errors.append('The uploaded file does not appear to be a valid image.')
            else:
                ext = avatar_file.filename.rsplit('.', 1)[1].lower()
                filename = f'user_{user_id}.{ext}'
                # Remove any previous avatar files for this user
                for old_ext in ALLOWED_EXT:
                    old_path = os.path.join(UPLOAD_FOLDER, f'user_{user_id}.{old_ext}')
                    if os.path.exists(old_path):
                        os.remove(old_path)
                avatar_file.save(os.path.join(UPLOAD_FOLDER, filename))
                new_avatar_rel = f'uploads/avatars/{filename}'

        if not errors:
            fields = 'username = ?, email = ?'
            params = [username, email]
            if new_password:
                fields += ', password_hash = ?'
                params.append(hash_password(new_password))
            if new_avatar_rel is not None:
                fields += ', avatar = ?'
                params.append(new_avatar_rel)
            params.append(user_id)
            try:
                conn = get_db()
                conn.execute(f'UPDATE users SET {fields} WHERE id = ?', params)
                conn.commit()
                conn.close()
                session['username'] = username
                if new_avatar_rel is not None:
                    session['avatar'] = new_avatar_rel
                flash('Profile updated successfully.', 'success')
                return redirect(url_for('profile'))
            except sqlite3.IntegrityError:
                conn.close()
                flash('That username or email is already taken.', 'danger')
        else:
            for err in errors:
                flash(err, 'danger')

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', [user_id]).fetchone()
    conn.close()
    # Keep session avatar in sync with DB on GET
    if request.method == 'GET':
        session['avatar'] = user['avatar'] if user['avatar'] else ''
    return render_template('profile.html', user=user)


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']

    # Read filter params
    start_date = request.args.get('start_date', '').strip()
    end_date   = request.args.get('end_date', '').strip()
    category   = request.args.get('category', '').strip()
    min_amount = request.args.get('min_amount', '').strip()
    max_amount = request.args.get('max_amount', '').strip()
    search     = request.args.get('search', '').strip()
    filters    = dict(start_date=start_date, end_date=end_date, category=category,
                      min_amount=min_amount, max_amount=max_amount, search=search)
    has_filter = any(filters.values())

    # Build filtered query
    query  = 'SELECT * FROM expenses WHERE user_id = ?'
    params = [user_id]
    if start_date:
        query += ' AND date >= ?'; params.append(start_date)
    if end_date:
        query += ' AND date <= ?'; params.append(end_date)
    if category:
        query += ' AND category = ?'; params.append(category)
    if min_amount:
        try: query += ' AND amount >= ?'; params.append(float(min_amount))
        except ValueError: pass
    if max_amount:
        try: query += ' AND amount <= ?'; params.append(float(max_amount))
        except ValueError: pass
    if search:
        query += ' AND (title LIKE ? OR notes LIKE ? OR tags LIKE ?)'
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    query += ' ORDER BY date DESC, created_at DESC'

    conn = get_db()
    user_settings = conn.execute(
        'SELECT COALESCE(monthly_budget, 0) AS monthly_budget FROM users WHERE id = ?', [user_id]
    ).fetchone()
    monthly_budget = float(user_settings['monthly_budget'] or 0)

    expenses = conn.execute(query, params).fetchall()

    # Overall stats (unfiltered)
    stats = conn.execute(
        'SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as count, COALESCE(AVG(amount),0) as avg '
        'FROM expenses WHERE user_id = ?', [user_id]
    ).fetchone()

    current_month  = datetime.now().strftime('%Y-%m')
    monthly_total  = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id = ? AND strftime('%Y-%m', date)=?",
        [user_id, current_month]
    ).fetchone()[0]

    # Chart data — same filters as the expense table
    chart_where  = 'WHERE user_id = ?'
    chart_params = [user_id]
    if start_date:
        chart_where += ' AND date >= ?'; chart_params.append(start_date)
    if end_date:
        chart_where += ' AND date <= ?'; chart_params.append(end_date)
    if category:
        chart_where += ' AND category = ?'; chart_params.append(category)
    if min_amount:
        try: chart_where += ' AND amount >= ?'; chart_params.append(float(min_amount))
        except ValueError: pass
    if max_amount:
        try: chart_where += ' AND amount <= ?'; chart_params.append(float(max_amount))
        except ValueError: pass
    if search:
        chart_where += ' AND (title LIKE ? OR notes LIKE ? OR tags LIKE ?)'
        chart_params += [f'%{search}%', f'%{search}%', f'%{search}%']

    cat_agg_rows = conn.execute(
        f'SELECT category, COUNT(*) AS entries, SUM(amount) AS total FROM expenses {chart_where} '
        f'GROUP BY category ORDER BY total DESC', chart_params
    ).fetchall()
    monthly_rows = conn.execute(
        f"SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS total "
        f"FROM expenses {chart_where} GROUP BY month ORDER BY month ASC", chart_params
    ).fetchall()

    conn.close()

    # Keep category chart/table stable by always showing all known categories.
    cat_lookup = {
        r['category']: {
            'entries': int(r['entries'] or 0),
            'total': float(r['total'] or 0)
        }
        for r in cat_agg_rows
    }
    cat_rows = [
        {
            'category': cat,
            'entries': cat_lookup.get(cat, {}).get('entries', 0),
            'total': cat_lookup.get(cat, {}).get('total', 0.0)
        }
        for cat in CATEGORIES
    ]
    # Preserve visibility for legacy/custom categories already in DB.
    for r in cat_agg_rows:
        if r['category'] not in CATEGORIES:
            cat_rows.append({
                'category': r['category'],
                'entries': int(r['entries'] or 0),
                'total': float(r['total'] or 0)
            })

    filtered_total = sum(e['amount'] for e in expenses)
    has_spending_view_data = bool(expenses)

    # Budget-only alert behavior: show alert only when set budget is crossed.
    alert_total = filtered_total if has_filter else float(monthly_total or 0)
    active_scope = 'Filtered spending' if has_filter else 'This month spending'
    budget_alerts = []
    budget_risk_counts = {'Low': 0, 'Medium': 0, 'High': 0}

    if monthly_budget > 0 and alert_total > monthly_budget:
        increase_pct = _pct_change(alert_total, monthly_budget)
        increase_pct = increase_pct if increase_pct is not None else 0.0
        risk = classify_risk(increase_pct)
        budget_alerts.append({
            'risk': risk,
            'kind': 'budget_crossed',
            'category': 'Budget',
            'increase_pct': round(increase_pct, 1),
            'message': f'{active_scope} crossed your budget (${monthly_budget:.2f}).'
        })
        budget_risk_counts[risk] += 1

    budget_risk_level = 'Low'
    if any(a['risk'] == 'High' for a in budget_alerts):
        budget_risk_level = 'High'
    elif any(a['risk'] == 'Medium' for a in budget_alerts):
        budget_risk_level = 'Medium'

    spending_alerts = {
        'alerts': budget_alerts,
        'risk_counts': budget_risk_counts,
        'risk_level': budget_risk_level,
        'risk_score': {'Low': 30, 'Medium': 65, 'High': 90}[budget_risk_level],
        'has_enough_history': True,
        'fallback_message': ''
    }

    return render_template('expenses/dashboard.html',
        expenses=expenses,
        total_all=stats['total'],
        expense_count=stats['count'],
        avg_expense=stats['avg'],
        monthly_total=monthly_total,
        filtered_total=filtered_total,
        categories=CATEGORIES,
        monthly_budget=monthly_budget,
        has_filter=has_filter,
        filters=filters,
        cat_rows=cat_rows,
        cat_labels=[r['category'] for r in cat_rows],
        cat_values=[r['total'] for r in cat_rows],
        monthly_labels=[r['month'] for r in monthly_rows],
        monthly_values=[r['total'] for r in monthly_rows],
        has_spending_view_data=has_spending_view_data,
        spending_alerts=spending_alerts['alerts'],
        spending_risk_level=spending_alerts['risk_level'],
        spending_risk_score=spending_alerts['risk_score'],
        spending_risk_counts=spending_alerts['risk_counts'],
        spending_has_history=spending_alerts['has_enough_history'],
        spending_fallback_message=spending_alerts['fallback_message'],
    )


@app.route('/budget/set', methods=['POST'])
@login_required
def set_monthly_budget():
    user_id = session['user_id']
    raw_budget = request.form.get('monthly_budget', '').strip()

    try:
        if raw_budget == '':
            budget_value = 0.0
        else:
            budget_value = float(raw_budget)
        if budget_value < 0:
            raise ValueError()
    except ValueError:
        flash('Please enter a valid monthly budget amount.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db()
    conn.execute('UPDATE users SET monthly_budget = ? WHERE id = ?', [budget_value, user_id])
    conn.commit()
    conn.close()

    if budget_value > 0:
        flash(f'Monthly budget set to ${budget_value:.2f}.', 'success')
    else:
        flash('Monthly budget cleared.', 'info')
    return redirect(url_for('dashboard'))


# ── Add Expense ────────────────────────────────────────────────────────────────

@app.route('/expense/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    if request.method == 'POST':
        title    = request.form.get('title', '').strip()
        amount   = request.form.get('amount', '').strip()
        date     = request.form.get('date', '').strip()
        category = request.form.get('category', '').strip()
        notes    = request.form.get('notes', '').strip()
        tags     = request.form.get('tags', '').strip()

        errors     = []
        amount_val = None
        if not title:
            errors.append('Title is required.')
        try:
            amount_val = float(amount)
            if amount_val <= 0:
                errors.append('Amount must be greater than zero.')
        except (ValueError, TypeError):
            errors.append('A valid positive amount is required.')
        if not date:
            errors.append('Date is required.')
        else:
            try:
                datetime.strptime(date, '%Y-%m-%d')
            except ValueError:
                errors.append('Invalid date format.')
        if category not in CATEGORIES:
            errors.append('Please select a valid category.')

        if not errors:
            conn = get_db()
            conn.execute(
                'INSERT INTO expenses (user_id, title, amount, date, category, notes, tags) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (session['user_id'], title, amount_val, date, category, notes, tags)
            )
            conn.commit()
            conn.close()
            flash('Expense added successfully!', 'success')
            return redirect(url_for('dashboard'))

        for err in errors:
            flash(err, 'danger')

    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('expenses/add_expense.html', categories=CATEGORIES,
                           today=today, form=request.form)


# ── Edit Expense ───────────────────────────────────────────────────────────────

@app.route('/expense/edit/<int:expense_id>', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    conn    = get_db()
    expense = conn.execute(
        'SELECT * FROM expenses WHERE id = ? AND user_id = ?',
        [expense_id, session['user_id']]
    ).fetchone()
    conn.close()

    if not expense:
        flash('Expense not found.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        title    = request.form.get('title', '').strip()
        amount   = request.form.get('amount', '').strip()
        date     = request.form.get('date', '').strip()
        category = request.form.get('category', '').strip()
        notes    = request.form.get('notes', '').strip()
        tags     = request.form.get('tags', '').strip()

        errors     = []
        amount_val = None
        if not title:
            errors.append('Title is required.')
        try:
            amount_val = float(amount)
            if amount_val <= 0:
                errors.append('Amount must be greater than zero.')
        except (ValueError, TypeError):
            errors.append('A valid positive amount is required.')
        if not date:
            errors.append('Date is required.')
        else:
            try:
                datetime.strptime(date, '%Y-%m-%d')
            except ValueError:
                errors.append('Invalid date format.')
        if category not in CATEGORIES:
            errors.append('Please select a valid category.')

        if not errors:
            conn = get_db()
            conn.execute(
                "UPDATE expenses SET title=?, amount=?, date=?, category=?, notes=?, tags=?, "
                "updated_at=datetime('now') WHERE id=? AND user_id=?",
                (title, amount_val, date, category, notes, tags, expense_id, session['user_id'])
            )
            conn.commit()
            conn.close()
            flash('Expense updated successfully.', 'success')
            return redirect(url_for('dashboard'))

        for err in errors:
            flash(err, 'danger')

    return render_template('expenses/edit_expense.html', expense=expense, categories=CATEGORIES)


# ── Delete Expense ─────────────────────────────────────────────────────────────

@app.route('/expense/delete/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    conn   = get_db()
    result = conn.execute(
        'DELETE FROM expenses WHERE id = ? AND user_id = ?',
        [expense_id, session['user_id']]
    )
    conn.commit()
    conn.close()
    if result.rowcount:
        flash('Expense deleted.', 'success')
    else:
        flash('Expense not found.', 'danger')
    return redirect(url_for('dashboard'))


# ── Admin: Dashboard ───────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    users = conn.execute(
        'SELECT u.id, u.username, u.email, u.created_at, '
        'COUNT(e.id) AS expense_count, COALESCE(SUM(e.amount), 0) AS total_expenses '
        'FROM users u LEFT JOIN expenses e ON u.id = e.user_id '
        'WHERE u.is_admin = 0 GROUP BY u.id ORDER BY total_expenses DESC'
    ).fetchall()

    stats = conn.execute(
        'SELECT COUNT(DISTINCT user_id) AS total_users, COUNT(*) AS total_expenses, '
        'COALESCE(SUM(amount), 0) AS total_amount FROM expenses'
    ).fetchone()

    cat_rows = conn.execute(
        'SELECT category, SUM(amount) AS total FROM expenses GROUP BY category ORDER BY total DESC'
    ).fetchall()
    monthly_rows = conn.execute(
        "SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS total "
        "FROM expenses GROUP BY month ORDER BY month ASC LIMIT 12"
    ).fetchall()
    recent = conn.execute(
        'SELECT e.*, u.username FROM expenses e JOIN users u ON e.user_id = u.id '
        'ORDER BY e.created_at DESC LIMIT 10'
    ).fetchall()
    conn.close()

    return render_template('admin/dashboard.html',
        users=users,
        stats=stats,
        cat_labels=[r['category'] for r in cat_rows],
        cat_values=[r['total'] for r in cat_rows],
        monthly_labels=[r['month'] for r in monthly_rows],
        monthly_values=[r['total'] for r in monthly_rows],
        recent=recent,
    )


# ── Admin: User Expenses ───────────────────────────────────────────────────────

@app.route('/admin/user/<int:user_id>')
@admin_required
def admin_user_expenses(user_id):
    conn = get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE id = ? AND is_admin = 0', [user_id]
    ).fetchone()
    if not user:
        conn.close()
        flash('User not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    expenses = conn.execute(
        'SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC, created_at DESC', [user_id]
    ).fetchall()
    total = conn.execute(
        'SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE user_id = ?', [user_id]
    ).fetchone()[0]
    cat_rows = conn.execute(
        'SELECT category, SUM(amount) AS total FROM expenses WHERE user_id = ? '
        'GROUP BY category ORDER BY total DESC', [user_id]
    ).fetchall()
    conn.close()

    return render_template('admin/user_expenses.html',
        user=user,
        expenses=expenses,
        total=total,
        categories=CATEGORIES,
        cat_labels=[r['category'] for r in cat_rows],
        cat_values=[r['total'] for r in cat_rows],
    )


# ── Admin: Edit Expense ────────────────────────────────────────────────────────

@app.route('/admin/expense/edit/<int:expense_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_expense(expense_id):
    conn    = get_db()
    expense = conn.execute(
        'SELECT e.*, u.username FROM expenses e JOIN users u ON e.user_id = u.id WHERE e.id = ?',
        [expense_id]
    ).fetchone()
    conn.close()

    if not expense:
        flash('Expense not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        title    = request.form.get('title', '').strip()
        amount   = request.form.get('amount', '').strip()
        date     = request.form.get('date', '').strip()
        category = request.form.get('category', '').strip()
        notes    = request.form.get('notes', '').strip()
        tags     = request.form.get('tags', '').strip()

        errors     = []
        amount_val = None
        if not title:
            errors.append('Title is required.')
        try:
            amount_val = float(amount)
            if amount_val <= 0:
                errors.append('Amount must be greater than zero.')
        except (ValueError, TypeError):
            errors.append('A valid positive amount is required.')
        if not date:
            errors.append('Date is required.')
        else:
            try:
                datetime.strptime(date, '%Y-%m-%d')
            except ValueError:
                errors.append('Invalid date format.')
        if category not in CATEGORIES:
            errors.append('Please select a valid category.')

        if not errors:
            conn = get_db()
            conn.execute(
                "UPDATE expenses SET title=?, amount=?, date=?, category=?, notes=?, tags=?, "
                "updated_at=datetime('now') WHERE id=?",
                (title, amount_val, date, category, notes, tags, expense_id)
            )
            conn.commit()
            conn.close()
            flash('Expense updated.', 'success')
            return redirect(url_for('admin_user_expenses', user_id=expense['user_id']))

        for err in errors:
            flash(err, 'danger')

    return render_template('admin/edit_expense.html', expense=expense, categories=CATEGORIES)


# ── Admin: Delete Expense ──────────────────────────────────────────────────────

@app.route('/admin/expense/delete/<int:expense_id>', methods=['POST'])
@admin_required
def admin_delete_expense(expense_id):
    conn    = get_db()
    expense = conn.execute('SELECT user_id FROM expenses WHERE id = ?', [expense_id]).fetchone()
    if expense:
        uid = expense['user_id']
        conn.execute('DELETE FROM expenses WHERE id = ?', [expense_id])
        conn.commit()
        conn.close()
        flash('Expense deleted.', 'success')
        return redirect(url_for('admin_user_expenses', user_id=uid))
    conn.close()
    flash('Expense not found.', 'danger')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    if user_id == session.get('user_id'):
        flash('You cannot delete your own admin account from this interface.', 'danger')
        return redirect(url_for('admin_dashboard'))

    conn = get_db()
    user = conn.execute('SELECT id, is_admin FROM users WHERE id = ?', [user_id]).fetchone()
    if not user or user['is_admin']:
        conn.close()
        flash('User not found or cannot delete admin user.', 'danger')
        return redirect(url_for('admin_dashboard'))

    conn.execute('DELETE FROM users WHERE id = ?', [user_id])
    conn.commit()
    conn.close()
    flash('User deleted successfully. All their expenses have been removed.', 'success')
    return redirect(url_for('admin_dashboard'))


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
