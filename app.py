import os
import re
import secrets
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from mysql.connector import Error, IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from db import execute_query, fetch_one

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,50}$")

# Sample cards for the homepage layout until the catalogue is connected in Stage 3.
SAMPLE_FEATURED = [
    {
        "title": "The Quiet Atlas",
        "author": "Meera Kulkarni",
        "genre": "Literary Fiction",
        "rating": "4.6",
        "reviews": 128,
        "cover_tone": "terracotta",
    },
    {
        "title": "Night Train to Goa",
        "author": "Rahul D'Souza",
        "genre": "Mystery",
        "rating": "4.3",
        "reviews": 86,
        "cover_tone": "ink",
    },
    {
        "title": "A Garden of Small Hours",
        "author": "Priya Nair",
        "genre": "Poetry",
        "rating": "4.8",
        "reviews": 54,
        "cover_tone": "sage",
    },
    {
        "title": "Circuit of Stars",
        "author": "Arjun Patel",
        "genre": "Science Fiction",
        "rating": "4.1",
        "reviews": 201,
        "cover_tone": "lilac",
    },
]

SAMPLE_BOOKS = [
    {
        "title": "Letters from a Hill Station",
        "author": "Ananya Bose",
        "genre": "Romance",
        "rating": "4.4",
        "reviews": 73,
        "cover_tone": "coral",
    },
    {
        "title": "The Last Typesetter",
        "author": "Vikram Sethi",
        "genre": "Historical",
        "rating": "4.7",
        "reviews": 142,
        "cover_tone": "ink",
    },
    {
        "title": "Salt and River Stones",
        "author": "Leela Menon",
        "genre": "Memoir",
        "rating": "4.2",
        "reviews": 39,
        "cover_tone": "sage",
    },
    {
        "title": "When the Library Closed",
        "author": "Farah Iqbal",
        "genre": "Mystery",
        "rating": "4.5",
        "reviews": 97,
        "cover_tone": "terracotta",
    },
    {
        "title": "Paper Boats in July",
        "author": "Kabir Raman",
        "genre": "Young Adult",
        "rating": "4.0",
        "reviews": 61,
        "cover_tone": "lilac",
    },
    {
        "title": "The Cartographer's Daughter",
        "author": "Sana Qureshi",
        "genre": "Adventure",
        "rating": "4.6",
        "reviews": 118,
        "cover_tone": "coral",
    },
    {
        "title": "Between Two Monsoons",
        "author": "Nitin Rao",
        "genre": "Literary Fiction",
        "rating": "3.9",
        "reviews": 44,
        "cover_tone": "sage",
    },
    {
        "title": "A Short History of Rain",
        "author": "Ishita Ghosh",
        "genre": "Poetry",
        "rating": "4.9",
        "reviews": 27,
        "cover_tone": "ink",
    },
]

SAMPLE_GENRES = [
    "All",
    "Literary Fiction",
    "Mystery",
    "Science Fiction",
    "Romance",
    "Poetry",
    "Memoir",
    "Historical",
]


def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


def csrf_ok():
    sent = request.form.get("csrf_token", "")
    saved = session.get("csrf_token", "")
    return bool(sent) and secrets.compare_digest(sent, saved)


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        return fetch_one(
            "SELECT id, username, email, role FROM users WHERE id = %s",
            (user_id,),
        )
    except Error:
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not get_current_user():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        if user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_globals():
    user = get_current_user()
    return {
        "current_user": user,
        "is_logged_in": user is not None,
        "is_admin": bool(user and user["role"] == "admin"),
        "csrf_token": get_csrf_token(),
    }


@app.errorhandler(403)
def forbidden(_error):
    return render_template("forbidden.html", current_page=""), 403



@app.route("/")
def home():
    return render_template(
        "home.html",
        featured_books=SAMPLE_FEATURED,
        books=SAMPLE_BOOKS,
        genres=SAMPLE_GENRES,
        current_page="home",
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if get_current_user():
        return redirect(url_for("home"))

    form = {"username": "", "email": ""}
    if request.method == "POST":
        if not csrf_ok():
            flash("The form expired. Please try again.", "warning")
            return redirect(url_for("register"))

        form["username"] = request.form.get("username", "").strip()
        form["email"] = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        error = validate_registration(form["username"], form["email"], password, confirm)
        if error:
            flash(error, "danger")
            return render_template("register.html", form=form, current_page="register")

        try:
            execute_query(
                """
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, 'user')
                """,
                (form["username"], form["email"], generate_password_hash(password)),
            )
        except IntegrityError:
            flash("That username or email is already registered.", "danger")
            return render_template("register.html", form=form, current_page="register")
        
        except Error as error:
            app.logger.exception("Registration database error: %s", error)
            flash("Could not reach the database. Please try again later.", "danger")
            return render_template("register.html", form=form, current_page="register")


        flash("Account created. You can log in now.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", form=form, current_page="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user():
        return redirect(url_for("home"))

    if request.method == "POST":
        if not csrf_ok():
            flash("The form expired. Please try again.", "warning")
            return redirect(url_for("login"))

        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        if not identifier or not password:
            flash("Enter your username or email and password.", "danger")
            return render_template("login.html", identifier=identifier, current_page="login")

        try:
            user = fetch_one(
                """
                SELECT id, username, email, password_hash, role
                FROM users
                WHERE username = %s OR email = %s
                """,
                (identifier, identifier.lower()),
            )
        except Error:
            flash("Could not reach the database. Please try again later.", "danger")
            return render_template("login.html", identifier=identifier, current_page="login")

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Incorrect username/email or password.", "danger")
            return render_template("login.html", identifier=identifier, current_page="login")

        session.clear()
        session["user_id"] = user["id"]
        session["csrf_token"] = secrets.token_hex(16)
        flash(f"Welcome back, {user['username']}.", "success")
        return redirect(url_for("home"))

    return render_template("login.html", identifier="", current_page="login")


@app.route("/logout", methods=["POST"])
def logout():
    if not csrf_ok():
        flash("The form expired. Please try again.", "warning")
        return redirect(url_for("home"))
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin.html", current_page="admin")



def validate_registration(username, email, password, confirm):
    if not USERNAME_PATTERN.fullmatch(username):
        return "Username must be 3-50 letters, numbers or underscores."
    if not EMAIL_PATTERN.fullmatch(email):
        return "Please enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password) > 128:
        return "Password is too long."
    if password != confirm:
        return "Password confirmation does not match."
    return None


if __name__ == "__main__":
    app.run(debug=True)
