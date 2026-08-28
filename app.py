from flask import Flask, render_template, request, redirect, session, flash, abort
import sqlite3
import os
import time
from werkzeug.utils import secure_filename
from model import analyze_sentiment
from image_check import check_app

app = Flask(__name__)
app.secret_key = "secret123"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def db():
    return sqlite3.connect("database.db")


def ensure_schema():
    conn = db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        password TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        sentiment TEXT
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

    columns = [row[1] for row in cursor.execute("PRAGMA table_info(apps)")]
    for column_name in ["link", "description", "image_url"]:
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE apps ADD COLUMN {column_name} TEXT")

    conn.commit()
    conn.close()


ensure_schema()


# ---------------- HOME ----------------
@app.route('/')
def home():
    return render_template("home.html")


# ---------------- REGISTER ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']

        conn = db()
        conn.execute("INSERT INTO users(username,password) VALUES (?,?)", (u, p))
        conn.commit()
        conn.close()

        flash("Account created successfully. Please log in.")
        return redirect('/login')

    return render_template("register.html")


# ---------------- LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']

        conn = db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?", (u, p)
        ).fetchone()
        conn.close()

        if user:
            session['user'] = u
            session['user_id'] = user[0]
            flash(f"Welcome back, {u}!")
            return redirect('/apps')

        flash("Invalid username or password.")

    return render_template("login.html")


# ---------------- VIEW APPS ----------------
@app.route('/apps')
def apps():
    if not session.get('user'):
        flash("Please log in to view applications.")
        return redirect('/login')

    conn = db()
    app_rows = conn.execute("SELECT * FROM apps ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("apps.html", apps=app_rows, username=session.get('user'))


# ---------------- APP DETAILS + REVIEW ----------------
@app.route('/apps/<int:app_id>', methods=['GET', 'POST'])
def app_detail(app_id):
    if not session.get('user'):
        flash("Please log in to view application details.")
        return redirect('/login')

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
            "INSERT INTO app_reviews(app_id, user_id, comment, sentiment) VALUES (?,?,?,?)",
            (app_id, session.get('user_id'), comment, sentiment)
        )
        conn.commit()

        rating_rows = conn.execute("SELECT sentiment FROM app_reviews WHERE app_id=?", (app_id,)).fetchall()
        score_map = {"Positive": 5, "Neutral": 3, "Negative": 1}
        average_score = sum(score_map.get(row[0], 3) for row in rating_rows) / len(rating_rows)
        conn.execute("UPDATE apps SET sentiment=?, rating=? WHERE id=?", (sentiment, round(average_score, 1), app_id))
        conn.commit()
        conn.close()

        flash("Review submitted successfully.")
        return redirect(f'/apps/{app_id}')

    return render_template("app_detail.html", app=app_row, comments=comments, username=session.get('user'))


# ---------------- ADD REVIEW ----------------
@app.route('/add_review', methods=['GET', 'POST'])
def add_review():
    if not session.get('user'):
        flash("Please log in before posting a review.")
        return redirect('/login')

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
                "INSERT INTO app_reviews(app_id, user_id, comment, sentiment) VALUES (?,?,?,?)",
                (app_id, session.get('user_id'), text, sentiment)
            )
            conn.commit()

            rating_rows = conn.execute("SELECT sentiment FROM app_reviews WHERE app_id=?", (app_id,)).fetchall()
            score_map = {"Positive": 5, "Neutral": 3, "Negative": 1}
            average_score = sum(score_map.get(row[0], 3) for row in rating_rows) / len(rating_rows)
            conn.execute("UPDATE apps SET sentiment=?, rating=? WHERE id=?", (sentiment, round(average_score, 1), app_id))
            conn.commit()
            conn.close()

            flash("Review submitted successfully.")
            return redirect(f'/apps/{app_id}')

        flash("Please complete all fields before submitting.")

    return render_template("add_review.html", apps=apps, username=session.get('user'))


# ---------------- IMAGE UPLOAD ----------------
@app.route('/upload_image', methods=['GET', 'POST'])
def upload_image():
    result = ""

    if request.method == 'POST':
        file = request.files['image']

        if file and file.filename:
            filename = str(int(time.time())) + "_" + secure_filename(file.filename)
            path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(path)
            result = check_app(path)
        else:
            result = "Please choose an image first."

    return render_template("upload.html", result=result)


# ---------------- USER DASHBOARD ----------------
@app.route('/dashboard')
def dashboard():
    if not session.get('user'):
        flash("Please log in first.")
        return redirect('/login')

    conn = db()
    user_reviews = conn.execute(
        "SELECT ar.comment, ar.sentiment, a.name FROM app_reviews ar LEFT JOIN apps a ON ar.app_id = a.id WHERE ar.user_id=? ORDER BY ar.id DESC",
        (session.get('user_id'),)
    ).fetchall()
    conn.close()

    total = len(user_reviews)
    neg = sum(1 for r in user_reviews if r[1] == "Negative")

    status = "No Data"
    if total > 0:
        status = "🚨 FRAUD APP" if neg / total > 0.5 else "✅ SAFE APP"

    return render_template(
        "dashboard.html",
        reviews=user_reviews,
        status=status,
        negative_count=neg,
        username=session.get('user')
    )


# ---------------- ADMIN DASHBOARD ----------------
@app.route('/admin/dashboard')
def admin_dashboard():
    conn = db()
    conn.row_factory = sqlite3.Row
    apps = conn.execute("SELECT * FROM apps ORDER BY id DESC").fetchall()
    users = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    feedback = conn.execute("""
        SELECT ar.id, u.username, a.name AS app_name, ar.comment, ar.sentiment
        FROM app_reviews ar
        LEFT JOIN users u ON ar.user_id = u.id
        LEFT JOIN apps a ON ar.app_id = a.id
        ORDER BY ar.id DESC
    """).fetchall()
    conn.close()

    return render_template("admin_dashboard.html", apps=apps, users=users, feedback=feedback)


# ---------------- AUTO SENTIMENT + RATING ----------------
def get_sentiment_and_rating(text):
    text = text.lower()

    positive_words = ["good", "great", "best", "nice", "excellent", "love"]
    negative_words = ["bad", "worst", "fake", "scam", "poor", "hate"]

    pos = sum(word in text for word in positive_words)
    neg = sum(word in text for word in negative_words)

    if pos > neg:
        return "Positive", 4.5
    elif neg > pos:
        return "Negative", 1.5
    else:
        return "Neutral", 3.0


# ---------------- ADD APP ----------------
@app.route('/admin/add_app', methods=['GET', 'POST'])
def add_app():
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        review = request.form['review']
        link = request.form.get('link', '')
        description = request.form.get('description', '')
        image_url = request.form.get('image_url', '')

        sentiment, rating = get_sentiment_and_rating(review)

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