import sqlite3

conn = sqlite3.connect("database.db")
c = conn.cursor()

# USERS TABLE
c.execute("""
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    password TEXT
)
""")

# REVIEWS TABLE
c.execute("""
CREATE TABLE IF NOT EXISTS reviews(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    sentiment TEXT
)
""")

# APPS TABLE
c.execute("""
CREATE TABLE IF NOT EXISTS apps(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    category TEXT,
    review TEXT,
    sentiment TEXT,
    rating REAL
)
""")

conn.commit()
conn.close()

print("Database created successfully!")