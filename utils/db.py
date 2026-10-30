import pyodbc
import hashlib

# Establish DB connection
def get_db_connection():
    return pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=SKYZEN\\HMI_PRO;'
        'DATABASE=HMI;'
        'Trusted_Connection=yes;'
    )

# Hash password using SHA-256
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Authenticate user against database
def authenticate_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_pw = hash_password(password)
    cursor.execute("SELECT * FROM Users WHERE username = ? AND password_hash = ?", (username, hashed_pw))
    user = cursor.fetchone()
    conn.close()
    return user
