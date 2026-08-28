from functools import wraps

from flask import Flask, render_template, request, redirect, session, flash, abort
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from model import analyze_sentiment, sentiment_score, score_to_rating

app = Flask(__name__)
app.secret_key = "secret123"

ADMIN_USERNAME = "admin"
ADMIN_DEFAULT_PASSWORD = "admin123"


def db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def _create_tables(cursor):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        password TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS apps(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        review TEXT,
        sentiment TEXT,
        rating REAL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_reviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id INTEGER,
        user_id INTEGER,
        comment TEXT,
        sentiment TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        ip_address TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)


def _add_column_if_missing(cursor, table, column, ddl):
    existing_columns = [row[1] for row in cursor.execute(f"PRAGMA table_info({table})")]
    if column not in existing_columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate_schema(cursor):
    """Brings tables created by an older version of this app up to the current schema."""
    _add_column_if_missing(cursor, "apps", "link", "TEXT")
    _add_column_if_missing(cursor, "apps", "description", "TEXT")
    _add_column_if_missing(cursor, "apps", "image_url", "TEXT")
    _add_column_if_missing(cursor, "apps", "status", "TEXT DEFAULT 'Unreviewed'")

    _add_column_if_missing(cursor, "app_reviews", "ip_address", "TEXT")

    _add_column_if_missing(cursor, "users", "role", "TEXT DEFAULT 'user'")
    _add_column_if_missing(cursor, "users", "created_at", "TEXT")
    cursor.execute("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")


def _seed_default_admin(cursor):
    admin_exists = cursor.execute("SELECT id FROM users WHERE role='admin'").fetchone()
    if not admin_exists:
        cursor.execute(
            "INSERT INTO users(username, password, role, created_at) VALUES (?,?,?,CURRENT_TIMESTAMP)",
            (ADMIN_USERNAME, generate_password_hash(ADMIN_DEFAULT_PASSWORD), "admin"),
        )


def ensure_schema():
    conn = db()
    cursor = conn.cursor()

    _create_tables(cursor)
    _migrate_schema(cursor)
    _seed_default_admin(cursor)

    conn.commit()
    conn.close()


ensure_schema()


def require_login(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user'):
            flash("Please log in to continue.")
            return redirect('/login')
        return view(*args, **kwargs)
    return wrapped


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user'):
            flash("Please log in to continue.")
            return redirect('/login')
        if session.get('role') != 'admin':
            flash("Admin access only.")
            return redirect('/dashboard')
        return view(*args, **kwargs)
    return wrapped


def recalculate_app_rating(conn, app_id):
    rating_rows = conn.execute("SELECT sentiment FROM app_reviews WHERE app_id=?", (app_id,)).fetchall()
    score_map = {"Positive": 5, "Neutral": 3, "Negative": 1}

    if not rating_rows:
        conn.execute("UPDATE apps SET sentiment=?, rating=? WHERE id=?", ("Neutral", 0.0, app_id))
        return

    average_score = sum(score_map.get(row[0], 3) for row in rating_rows) / len(rating_rows)

    if average_score >= 3.67:
        aggregate_sentiment = "Positive"
    elif average_score <= 2.33:
        aggregate_sentiment = "Negative"
    else:
        aggregate_sentiment = "Neutral"

    conn.execute(
        "UPDATE apps SET sentiment=?, rating=? WHERE id=?",
        (aggregate_sentiment, round(average_score, 1), app_id)
    )


# ---------------- HOME ----------------
@app.route('/')
def home():
    return render_template("home.html")


# ---------------- REGISTER ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = db()
        conn.execute(
            "INSERT INTO users(username,password,role,created_at) VALUES (?,?,?,CURRENT_TIMESTAMP)",
            (username, generate_password_hash(password), "user")
        )
        conn.commit()
        conn.close()

        flash("Account created successfully. Please log in.")
        return redirect('/login')

    return render_template("register.html")


# ---------------- LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = db()
        user = conn.execute(
            "SELECT id, username, password, role FROM users WHERE username=?", (username,)
        ).fetchone()

        authenticated = False
        if user:
            if check_password_hash(user['password'], password):
                authenticated = True
            elif user['password'] == password:
                # Legacy plaintext password from before hashing was added — accept it once,
                # then upgrade it to a hash so this branch never runs for this account again.
                authenticated = True
                conn.execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (generate_password_hash(password), user['id'])
                )
                conn.commit()

        conn.close()

        if authenticated:
            session['user'] = user['username']
            session['user_id'] = user['id']
            session['role'] = user['role']
            flash(f"Welcome back, {user['username']}!")
            return redirect('/apps')

        flash("Invalid username or password.")

    return render_template("login.html")


# ---------------- LOGOUT ----------------
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect('/')


# ---------------- VIEW APPS ----------------
@app.route('/apps')
@require_login
def apps():
    conn = db()
    app_rows = conn.execute("SELECT * FROM apps ORDER BY id DESC").fetchall()
    categories = [
        row[0] for row in conn.execute("SELECT DISTINCT category FROM apps WHERE category IS NOT NULL AND category != '' ORDER BY category")
    ]
    conn.close()
    return render_template("apps.html", apps=app_rows, categories=categories)


# ---------------- APP DETAILS + REVIEW ----------------
@app.route('/apps/<int:app_id>', methods=['GET', 'POST'])
@require_login
def app_detail(app_id):
    conn = db()
    app_row = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
    if not app_row:
        conn.close()
        abort(404)

    comments = conn.execute("""
        SELECT ar.comment, ar.sentiment, ar.created_at, u.username
        FROM app_reviews ar
        LEFT JOIN users u ON ar.user_id = u.id
        WHERE ar.app_id = ?
        ORDER BY ar.id DESC
    """, (app_id,)).fetchall()
    conn.close()

    if request.method == 'POST':
        comment = request.form.get('comment', '').strip()
        if not comment:
            flash("Please enter a review before submitting.")
            return redirect(f'/apps/{app_id}')

        sentiment = analyze_sentiment(comment)
        conn = db()
        conn.execute(
            "INSERT INTO app_reviews(app_id, user_id, comment, sentiment, ip_address) VALUES (?,?,?,?,?)",
            (app_id, session.get('user_id'), comment, sentiment, request.remote_addr)
        )
        conn.commit()

        recalculate_app_rating(conn, app_id)
        conn.commit()
        conn.close()

        flash("Review submitted successfully.")
        return redirect(f'/apps/{app_id}')

    return render_template("app_detail.html", app=app_row, comments=comments)


# ---------------- ADD REVIEW ----------------
@app.route('/add_review', methods=['GET', 'POST'])
@require_login
def add_review():
    conn = db()
    apps = conn.execute("SELECT id, name FROM apps ORDER BY id DESC").fetchall()
    conn.close()

    if request.method == 'POST':
        text = request.form.get('review', '').strip()
        app_id = request.form.get('app_id')
        if text and app_id:
            sentiment = analyze_sentiment(text)
            conn = db()
            conn.execute(
                "INSERT INTO app_reviews(app_id, user_id, comment, sentiment, ip_address) VALUES (?,?,?,?,?)",
                (app_id, session.get('user_id'), text, sentiment, request.remote_addr)
            )
            conn.commit()

            recalculate_app_rating(conn, app_id)
            conn.commit()
            conn.close()

            flash("Review submitted successfully.")
            return redirect(f'/apps/{app_id}')

        flash("Please complete all fields before submitting.")

    return render_template("add_review.html", apps=apps)


# ---------------- USER DASHBOARD ----------------
@app.route('/dashboard')
@require_login
def dashboard():
    conn = db()
    user_reviews = conn.execute("""
        SELECT ar.comment, ar.sentiment, a.name AS app_name
        FROM app_reviews ar
        LEFT JOIN apps a ON ar.app_id = a.id
        WHERE ar.user_id = ?
        ORDER BY ar.id DESC
    """, (session.get('user_id'),)).fetchall()
    conn.close()

    total = len(user_reviews)
    neg = sum(1 for review in user_reviews if review['sentiment'] == "Negative")

    status = "No Data"
    if total > 0:
        status = "🚨 FRAUD APP" if neg / total > 0.5 else "✅ SAFE APP"

    return render_template(
        "dashboard.html",
        reviews=user_reviews,
        status=status,
        negative_count=neg
    )


# ---------------- SYSTEM FEEDBACK ----------------
@app.route('/feedback', methods=['GET', 'POST'])
@require_login
def feedback():
    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        if not message:
            flash("Please write your feedback before submitting.")
            return redirect('/feedback')

        conn = db()
        conn.execute(
            "INSERT INTO system_feedback(user_id, message, ip_address) VALUES (?,?,?)",
            (session.get('user_id'), message, request.remote_addr)
        )
        conn.commit()
        conn.close()

        flash("Thank you, your feedback has been sent to the admin.")
        return redirect('/dashboard')

    return render_template("feedback.html")


# ---------------- ADMIN DASHBOARD ----------------
@app.route('/admin/dashboard')
@require_admin
def admin_dashboard():
    conn = db()
    apps = conn.execute("""
        SELECT a.*,
            COALESCE((SELECT COUNT(*) FROM app_reviews r WHERE r.app_id = a.id), 0) AS review_count,
            COALESCE((SELECT COUNT(*) FROM app_reviews r WHERE r.app_id = a.id AND r.sentiment = 'Negative'), 0) AS negative_count
        FROM apps a
        ORDER BY
            CASE WHEN (SELECT COUNT(*) FROM app_reviews r WHERE r.app_id = a.id) = 0 THEN 0
            ELSE CAST((SELECT COUNT(*) FROM app_reviews r WHERE r.app_id = a.id AND r.sentiment = 'Negative') AS FLOAT)
                 / (SELECT COUNT(*) FROM app_reviews r WHERE r.app_id = a.id)
            END DESC,
            a.id DESC
    """).fetchall()
    users = conn.execute("""
        SELECT u.id, u.username, u.role, u.created_at,
            COALESCE((SELECT COUNT(*) FROM app_reviews r WHERE r.user_id = u.id), 0) AS review_count,
            COALESCE((SELECT COUNT(*) FROM system_feedback f WHERE f.user_id = u.id), 0) AS feedback_count
        FROM users u
        ORDER BY u.id DESC
    """).fetchall()
    feedback = conn.execute("""
        SELECT ar.id, u.username, a.name AS app_name, ar.comment, ar.sentiment, ar.ip_address, ar.created_at,
            (SELECT COUNT(*) FROM app_reviews dup WHERE dup.app_id = ar.app_id AND dup.comment = ar.comment) AS dup_count
        FROM app_reviews ar
        LEFT JOIN users u ON ar.user_id = u.id
        LEFT JOIN apps a ON ar.app_id = a.id
        ORDER BY ar.id DESC
    """).fetchall()
    system_feedback = conn.execute("""
        SELECT sf.id, u.username, sf.message, sf.ip_address, sf.created_at
        FROM system_feedback sf
        LEFT JOIN users u ON sf.user_id = u.id
        ORDER BY sf.id DESC
    """).fetchall()
    conn.close()

    return render_template(
        "admin_dashboard.html",
        apps=apps,
        users=users,
        feedback=feedback,
        system_feedback=system_feedback
    )


# ---------------- ADMIN: FRAUD / GENUINE VERDICT ----------------
@app.route('/admin/apps/<int:app_id>/verdict', methods=['POST'])
@require_admin
def set_app_verdict(app_id):
    verdict = request.form.get('status')
    if verdict not in ("Genuine", "Fraud"):
        flash("Invalid verdict.")
        return redirect('/admin/dashboard')

    conn = db()
    conn.execute("UPDATE apps SET status=? WHERE id=?", (verdict, app_id))
    conn.commit()
    conn.close()

    flash(f"App marked as {verdict}.")
    return redirect('/admin/dashboard')


# ---------------- ADMIN: DELETE REVIEW ----------------
@app.route('/admin/reviews/<int:review_id>/delete', methods=['POST'])
@require_admin
def delete_review(review_id):
    conn = db()
    review = conn.execute("SELECT app_id FROM app_reviews WHERE id=?", (review_id,)).fetchone()
    if review:
        app_id = review['app_id']
        conn.execute("DELETE FROM app_reviews WHERE id=?", (review_id,))
        recalculate_app_rating(conn, app_id)
        conn.commit()
        flash("Review removed.")
    conn.close()

    return redirect('/admin/dashboard')


# ---------------- ADD APP ----------------
@app.route('/admin/add_app', methods=['GET', 'POST'])
@require_admin
def add_app():
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        review = request.form['review']
        link = request.form.get('link', '')
        description = request.form.get('description', '')
        image_url = request.form.get('image_url', '')

        sentiment = analyze_sentiment(review)
        rating = score_to_rating(sentiment_score(review))

        conn = db()
        conn.execute("""
            INSERT INTO apps(name,category,review,sentiment,rating,link,description,image_url)
            VALUES (?,?,?,?,?,?,?,?)
        """, (name, category, review, sentiment, rating, link, description, image_url))
        conn.commit()
        conn.close()

        flash("App record added successfully.")
        return redirect('/admin/dashboard')

    return render_template("add_app.html")


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)