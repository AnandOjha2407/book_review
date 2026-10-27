import os
import re
import secrets
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from mysql.connector import Error, IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from db import execute_query, fetch_all, fetch_one

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,50}$")
ALLOWED_RATINGS = [Decimal("1.0"), Decimal("1.5"), Decimal("2.0"), Decimal("2.5"),
                   Decimal("3.0"), Decimal("3.5"), Decimal("4.0"), Decimal("4.5"),
                   Decimal("5.0")]
COVER_TONES = ["terracotta", "ink", "sage", "lilac", "coral"]
ALLOWED_COVER_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_COVER_BYTES = 2 * 1024 * 1024
PAGE_SIZE = 12
UPLOAD_FOLDER = Path(__file__).with_name("uploads")
CURRENT_YEAR = datetime.now().year

BOOKS_WITH_STATS = """
    SELECT b.*, stats.avg_rating, stats.review_count
    FROM books b
    LEFT JOIN (
        SELECT book_id, AVG(rating) AS avg_rating, COUNT(*) AS review_count
        FROM reviews
        WHERE status = 'approved'
        GROUP BY book_id
    ) stats ON stats.book_id = b.id
"""
REVIEW_SORTS = {
    "newest": "r.created_at DESC",
    "oldest": "r.created_at ASC",
    "highest": "r.rating DESC, r.created_at DESC",
    "lowest": "r.rating ASC, r.created_at DESC",
    "helpful": "helpful_count DESC, r.created_at DESC",
}
READING_STATUSES = {
    "want_to_read": "Want to Read",
    "currently_reading": "Currently Reading",
    "finished": "Finished",
}


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
        user = fetch_one(
            """
            SELECT id, username, email, role, is_active, created_at
            FROM users WHERE id = %s
            """,
            (user_id,),
        )
        if user and not user.get("is_active", 1):
            session.clear()
            return None
        return user
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


def cover_tone(book_id):
    return COVER_TONES[int(book_id) % len(COVER_TONES)]


def cover_src(book):
    filename = book.get("cover_filename")
    if filename:
        return url_for("uploaded_cover", filename=filename)
    url = book.get("cover_url")
    if url:
        return url
    return None


def format_rating(value):
    if value is None:
        return None
    return f"{float(value):.1f}"


def decorate_book(book):
    if not book:
        return book
    book["cover_tone"] = cover_tone(book["id"])
    book["cover_src"] = cover_src(book)
    book["avg_rating_display"] = format_rating(book.get("avg_rating"))
    book["review_count"] = int(book.get("review_count") or 0)
    return book


def parse_rating(value):
    try:
        rating = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return None
    if rating not in ALLOWED_RATINGS:
        return None
    return rating


def book_stats_row(book_id):
    return fetch_one(BOOKS_WITH_STATS + " WHERE b.id = %s", (book_id,))


def list_genres():
    rows = fetch_all("SELECT DISTINCT genre FROM books ORDER BY genre")
    return [row["genre"] for row in rows]


def query_books(search="", genre="", limit=None, offset=0):
    sql = BOOKS_WITH_STATS + " WHERE 1=1"
    params = []
    if search:
        sql += " AND (b.title LIKE %s OR b.author LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like])
    if genre:
        sql += " AND b.genre = %s"
        params.append(genre)
    sql += " ORDER BY b.title ASC"
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params.extend([int(limit), int(offset)])
    return [decorate_book(row) for row in fetch_all(sql, tuple(params))]


def review_sort_clause(sort_key):
    return REVIEW_SORTS.get(sort_key, REVIEW_SORTS["newest"])


def attach_review_extras(reviews, user):
    if not reviews:
        return reviews
    review_ids = [row["id"] for row in reviews]
    placeholders = ", ".join(["%s"] * len(review_ids))
    comments = fetch_all(
        f"""
        SELECT c.id, c.review_id, c.user_id, c.comment_text, c.created_at, u.username
        FROM review_comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.review_id IN ({placeholders})
        ORDER BY c.created_at ASC
        """,
        tuple(review_ids),
    )
    comments_by_review = {}
    for comment in comments:
        comments_by_review.setdefault(comment["review_id"], []).append(comment)
    voted_ids = set()
    if user:
        votes = fetch_all(
            f"""
            SELECT review_id FROM review_votes
            WHERE user_id = %s AND review_id IN ({placeholders})
            """,
            (user["id"], *review_ids),
        )
        voted_ids = {row["review_id"] for row in votes}
    for review in reviews:
        review["comments"] = comments_by_review.get(review["id"], [])
        review["user_voted"] = review["id"] in voted_ids
        review["helpful_count"] = int(review.get("helpful_count") or 0)
    return reviews


def top_rated_books(limit=4):
    rows = fetch_all(
        BOOKS_WITH_STATS
        + """
        WHERE stats.review_count >= 1
        ORDER BY stats.avg_rating DESC, stats.review_count DESC
        LIMIT %s
        """,
        (limit,),
    )
    return [decorate_book(row) for row in rows]


def trending_books(limit=4):
    rows = fetch_all(
        """
        SELECT b.*, stats.avg_rating, stats.review_count,
               COALESCE(recent.recent_count, 0) AS recent_count
        FROM books b
        LEFT JOIN (
            SELECT book_id, AVG(rating) AS avg_rating, COUNT(*) AS review_count
            FROM reviews
            WHERE status = 'approved'
            GROUP BY book_id
        ) stats ON stats.book_id = b.id
        LEFT JOIN (
            SELECT book_id, COUNT(*) AS recent_count
            FROM reviews
            WHERE status = 'approved'
              AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY book_id
        ) recent ON recent.book_id = b.id
        WHERE COALESCE(recent.recent_count, 0) > 0
        ORDER BY recent.recent_count DESC, stats.avg_rating DESC
        LIMIT %s
        """,
        (limit,),
    )
    return [decorate_book(row) for row in rows]


def recent_books(limit=8):
    rows = fetch_all(
        BOOKS_WITH_STATS + " ORDER BY b.created_at DESC LIMIT %s",
        (limit,),
    )
    return [decorate_book(row) for row in rows]


def popular_books(limit=4, exclude_ids=None):
    sql = BOOKS_WITH_STATS + " WHERE COALESCE(stats.review_count, 0) > 0"
    params = []
    if exclude_ids:
        placeholders = ", ".join(["%s"] * len(exclude_ids))
        sql += f" AND b.id NOT IN ({placeholders})"
        params.extend(exclude_ids)
    sql += " ORDER BY stats.review_count DESC, stats.avg_rating DESC LIMIT %s"
    params.append(limit)
    return [decorate_book(row) for row in fetch_all(sql, tuple(params))]


def recommended_books_for(user, limit=4):
    """Books in genres the user rated 4+ (approved). Fallback: popular books."""
    exclude_rows = fetch_all(
        """
        SELECT book_id FROM reviews WHERE user_id = %s
        UNION
        SELECT book_id FROM reading_list WHERE user_id = %s
        """,
        (user["id"], user["id"]),
    )
    exclude_ids = [row["book_id"] for row in exclude_rows]
    liked = fetch_all(
        """
        SELECT b.genre
        FROM reviews r
        JOIN books b ON b.id = r.book_id
        WHERE r.user_id = %s AND r.status = 'approved' AND r.rating >= 4
        """,
        (user["id"],),
    )
    genres = list({row["genre"] for row in liked})
    if genres:
        placeholders = ", ".join(["%s"] * len(genres))
        sql = BOOKS_WITH_STATS + f" WHERE b.genre IN ({placeholders})"
        params = list(genres)
        if exclude_ids:
            exclude_ph = ", ".join(["%s"] * len(exclude_ids))
            sql += f" AND b.id NOT IN ({exclude_ph})"
            params.extend(exclude_ids)
        sql += " ORDER BY COALESCE(stats.avg_rating, 0) DESC, b.title ASC LIMIT %s"
        params.append(limit)
        rows = fetch_all(sql, tuple(params))
        if rows:
            return [decorate_book(row) for row in rows], "genre"
    fallback = popular_books(limit, exclude_ids)
    if fallback:
        return fallback, "popular"
    return recent_books(limit), "recent"


def count_books(search="", genre=""):
    sql = "SELECT COUNT(*) AS total FROM books b WHERE 1=1"
    params = []
    if search:
        sql += " AND (b.title LIKE %s OR b.author LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like])
    if genre:
        sql += " AND b.genre = %s"
        params.append(genre)
    row = fetch_one(sql, tuple(params))
    return int(row["total"] if row else 0)


def allowed_cover_bytes(header):
    if header.startswith(b"\xff\xd8\xff"):
        return True
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return True
    if header[0:4] == b"RIFF" and header[8:12] == b"WEBP":
        return True
    return False


def save_cover_file(file_storage):
    if not file_storage or not file_storage.filename:
        return None, None
    filename = secure_filename(file_storage.filename)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_COVER_EXTS:
        return None, "Cover images must be JPG, PNG, GIF or WEBP."
    data = file_storage.read()
    if len(data) > MAX_COVER_BYTES:
        return None, "Cover images must be 2 MB or smaller."
    if not allowed_cover_bytes(data[:16]):
        return None, "That file does not look like a valid image."
    stored_name = f"{uuid.uuid4().hex}{extension}"
    UPLOAD_FOLDER.mkdir(exist_ok=True)
    (UPLOAD_FOLDER / stored_name).write_bytes(data)
    return stored_name, None


def delete_cover_file(filename):
    if not filename:
        return
    path = UPLOAD_FOLDER / secure_filename(filename)
    if path.is_file() and path.parent == UPLOAD_FOLDER:
        path.unlink()


def validate_book_form(form):
    title = form.get("title", "").strip()
    author = form.get("author", "").strip()
    genre = form.get("genre", "").strip()
    description = form.get("description", "").strip()
    isbn = form.get("isbn", "").strip()
    publisher = form.get("publisher", "").strip()
    year_raw = form.get("publication_year", "").strip()
    cover_url = form.get("cover_url", "").strip()

    if not title or len(title) > 200:
        return None, "Enter a title of up to 200 characters."
    if not author or len(author) > 200:
        return None, "Enter an author of up to 200 characters."
    if not genre or len(genre) > 80:
        return None, "Enter a genre of up to 80 characters."
    if isbn and len(isbn) > 20:
        return None, "ISBN must be 20 characters or fewer."
    if publisher and len(publisher) > 200:
        return None, "Publisher must be 200 characters or fewer."
    if cover_url and not (cover_url.startswith("http://") or cover_url.startswith("https://")):
        return None, "Cover URL must start with http:// or https://."
    if cover_url and len(cover_url) > 500:
        return None, "Cover URL is too long."

    year = None
    if year_raw:
        if not year_raw.isdigit() or not (1000 <= int(year_raw) <= CURRENT_YEAR + 1):
            return None, "Enter a valid publication year."
        year = int(year_raw)

    return {
        "title": title,
        "author": author,
        "genre": genre,
        "description": description or None,
        "isbn": isbn or None,
        "publisher": publisher or None,
        "publication_year": year,
        "cover_url": cover_url or None,
    }, None


def empty_book_form():
    return {
        "title": "",
        "author": "",
        "genre": "",
        "description": "",
        "isbn": "",
        "publisher": "",
        "publication_year": "",
        "cover_url": "",
    }


def book_to_form(book):
    return {
        "title": book.get("title") or "",
        "author": book.get("author") or "",
        "genre": book.get("genre") or "",
        "description": book.get("description") or "",
        "isbn": book.get("isbn") or "",
        "publisher": book.get("publisher") or "",
        "publication_year": book.get("publication_year") or "",
        "cover_url": book.get("cover_url") or "",
    }


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


@app.errorhandler(404)
def not_found(_error):
    return render_template("not_found.html", current_page=""), 404


@app.route("/")
def home():
    user = get_current_user()
    try:
        featured = top_rated_books(4)
        trending = trending_books(4)
        latest = recent_books(8)
        genres = list_genres()
        recommended, recommend_reason = [], None
        if user:
            recommended, recommend_reason = recommended_books_for(user, 4)
        elif featured:
            recommended, recommend_reason = featured, "popular"
    except Error as error:
        app.logger.exception("Homepage database error: %s", error)
        flash("Could not load books from the database.", "danger")
        featured, trending, latest, genres, recommended, recommend_reason = [], [], [], [], [], None
    return render_template(
        "home.html",
        featured_books=featured,
        trending_books=trending,
        books=latest,
        recommended_books=recommended,
        recommend_reason=recommend_reason,
        genres=genres,
        current_page="home",
    )


@app.route("/books")
def books():
    search = request.args.get("q", "").strip()
    genre = request.args.get("genre", "").strip()
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1
    offset = (page - 1) * PAGE_SIZE
    try:
        total = count_books(search, genre)
        book_rows = query_books(search, genre, PAGE_SIZE, offset)
        genres = list_genres()
    except Error as error:
        app.logger.exception("Catalogue database error: %s", error)
        flash("Could not load the book catalogue.", "danger")
        total, book_rows, genres = 0, [], []
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    return render_template(
        "books.html",
        books=book_rows,
        genres=genres,
        search=search,
        selected_genre=genre,
        page=page,
        total_pages=total_pages,
        total=total,
        current_page="books",
    )


@app.route("/books/<int:book_id>")
def book_detail(book_id):
    user = get_current_user()
    sort_key = request.args.get("sort", "newest")
    if sort_key not in REVIEW_SORTS:
        sort_key = "newest"
    try:
        book = book_stats_row(book_id)
        if not book:
            abort(404)
        order_sql = review_sort_clause(sort_key)
        reviews = fetch_all(
            f"""
            SELECT r.id, r.user_id, r.rating, r.review_text, r.is_spoiler, r.created_at,
                   u.username, COALESCE(v.helpful_count, 0) AS helpful_count
            FROM reviews r
            JOIN users u ON u.id = r.user_id
            LEFT JOIN (
                SELECT review_id, COUNT(*) AS helpful_count
                FROM review_votes
                GROUP BY review_id
            ) v ON v.review_id = r.id
            WHERE r.book_id = %s AND r.status = 'approved'
            ORDER BY {order_sql}
            """,
            (book_id,),
        )
        reviews = attach_review_extras(reviews, user)
        own_review = None
        list_entry = None
        if user:
            own_review = fetch_one(
                """
                SELECT id, rating, review_text, is_spoiler, status, created_at, updated_at
                FROM reviews
                WHERE user_id = %s AND book_id = %s
                """,
                (user["id"], book_id),
            )
            list_entry = fetch_one(
                "SELECT id, status FROM reading_list WHERE user_id = %s AND book_id = %s",
                (user["id"], book_id),
            )
    except Error as error:
        app.logger.exception("Book detail database error: %s", error)
        flash("Could not load this book.", "danger")
        return redirect(url_for("books"))

    return render_template(
        "book_detail.html",
        book=decorate_book(book),
        reviews=reviews,
        own_review=own_review,
        list_entry=list_entry,
        reading_statuses=READING_STATUSES,
        ratings=ALLOWED_RATINGS,
        sort_key=sort_key,
        current_page="books",
    )


@app.route("/books/<int:book_id>/reviews", methods=["POST"])
@login_required
def save_review(book_id):
    user = get_current_user()
    if not csrf_ok():
        flash("The form expired. Please try again.", "warning")
        return redirect(url_for("book_detail", book_id=book_id))

    book = fetch_one("SELECT id FROM books WHERE id = %s", (book_id,))
    if not book:
        abort(404)

    rating = parse_rating(request.form.get("rating", ""))
    text = request.form.get("review_text", "").strip()
    is_spoiler = 1 if request.form.get("is_spoiler") else 0
    if rating is None:
        flash("Choose a rating from 1 to 5 in half-star steps.", "danger")
        return redirect(url_for("book_detail", book_id=book_id))
    if len(text) < 10:
        flash("Please write a review of at least 10 characters.", "danger")
        return redirect(url_for("book_detail", book_id=book_id))
    if len(text) > 5000:
        flash("Reviews must be 5000 characters or fewer.", "danger")
        return redirect(url_for("book_detail", book_id=book_id))

    existing = fetch_one(
        "SELECT id FROM reviews WHERE user_id = %s AND book_id = %s",
        (user["id"], book_id),
    )
    try:
        if existing:
            execute_query(
                """
                UPDATE reviews
                SET rating = %s, review_text = %s, is_spoiler = %s, status = 'pending'
                WHERE id = %s AND user_id = %s
                """,
                (str(rating), text, is_spoiler, existing["id"], user["id"]),
            )
            flash("Your review was updated and is waiting for approval.", "success")
        else:
            execute_query(
                """
                INSERT INTO reviews (user_id, book_id, rating, review_text, is_spoiler, status)
                VALUES (%s, %s, %s, %s, %s, 'pending')
                """,
                (user["id"], book_id, str(rating), text, is_spoiler),
            )
            flash("Your review was submitted and is waiting for approval.", "success")
    except IntegrityError:
        flash("You already have a review for this book.", "danger")
    except Error as error:
        app.logger.exception("Review save error: %s", error)
        flash("Could not save your review.", "danger")
    return redirect(url_for("book_detail", book_id=book_id))


@app.route("/reviews/<int:review_id>/delete", methods=["POST"])
@login_required
def delete_review(review_id):
    user = get_current_user()
    if not csrf_ok():
        flash("The form expired. Please try again.", "warning")
        return redirect(url_for("my_reviews"))

    review = fetch_one("SELECT id, user_id, book_id FROM reviews WHERE id = %s", (review_id,))
    if not review:
        abort(404)
    if review["user_id"] != user["id"] and user["role"] != "admin":
        abort(403)
    try:
        execute_query("DELETE FROM reviews WHERE id = %s", (review_id,))
        flash("The review was deleted.", "success")
    except Error as error:
        app.logger.exception("Review delete error: %s", error)
        flash("Could not delete the review.", "danger")
    next_page = request.form.get("next")
    if next_page == "admin":
        return redirect(url_for("admin_dashboard"))
    if next_page == "book":
        return redirect(url_for("book_detail", book_id=review["book_id"]))
    return redirect(url_for("my_reviews"))


@app.route("/books/<int:book_id>/reading-list", methods=["POST"])
@login_required
def toggle_reading_list(book_id):
    user = get_current_user()
    if not csrf_ok():
        flash("The form expired. Please try again.", "warning")
        return redirect(url_for("book_detail", book_id=book_id))
    book = fetch_one("SELECT id FROM books WHERE id = %s", (book_id,))
    if not book:
        abort(404)
    action = request.form.get("action", "add")
    status = request.form.get("status", "want_to_read")
    if status not in READING_STATUSES:
        status = "want_to_read"
    try:
        if action == "remove":
            execute_query(
                "DELETE FROM reading_list WHERE user_id = %s AND book_id = %s",
                (user["id"], book_id),
            )
            flash("Removed from your reading list.", "success")
        else:
            execute_query(
                """
                INSERT INTO reading_list (user_id, book_id, status)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE status = VALUES(status)
                """,
                (user["id"], book_id, status),
            )
            flash("Reading list updated.", "success")
    except Error as error:
        app.logger.exception("Reading list error: %s", error)
        flash("Could not update your reading list.", "danger")
    next_page = request.form.get("next")
    if next_page == "list":
        return redirect(url_for("reading_list", status=request.form.get("filter_status", "")))
    return redirect(url_for("book_detail", book_id=book_id, sort=request.args.get("sort", "")))


@app.route("/my-reviews")
@login_required
def my_reviews():
    user = get_current_user()
    try:
        reviews = fetch_all(
            """
            SELECT r.id, r.rating, r.review_text, r.is_spoiler, r.status,
                   r.created_at, r.updated_at, b.id AS book_id, b.title, b.author
            FROM reviews r
            JOIN books b ON b.id = r.book_id
            WHERE r.user_id = %s
            ORDER BY r.updated_at DESC
            """,
            (user["id"],),
        )
    except Error as error:
        app.logger.exception("My reviews error: %s", error)
        flash("Could not load your reviews.", "danger")
        reviews = []
    return render_template("my_reviews.html", reviews=reviews, current_page="my_reviews")


@app.route("/reading-list")
@login_required
def reading_list():
    user = get_current_user()
    status_filter = request.args.get("status", "").strip()
    sql = """
        SELECT b.*, stats.avg_rating, stats.review_count, rl.status AS list_status
        FROM books b
        LEFT JOIN (
            SELECT book_id, AVG(rating) AS avg_rating, COUNT(*) AS review_count
            FROM reviews
            WHERE status = 'approved'
            GROUP BY book_id
        ) stats ON stats.book_id = b.id
        JOIN reading_list rl ON rl.book_id = b.id
        WHERE rl.user_id = %s
    """
    params = [user["id"]]
    if status_filter in READING_STATUSES:
        sql += " AND rl.status = %s"
        params.append(status_filter)
    sql += " ORDER BY rl.created_at DESC"
    try:
        books = fetch_all(sql, tuple(params))
        for book in books:
            decorate_book(book)
            book["reading_status"] = book.get("list_status")
            book["reading_status_label"] = READING_STATUSES.get(book.get("list_status"), "")
    except Error as error:
        app.logger.exception("Reading list error: %s", error)
        flash("Could not load your reading list.", "danger")
        books = []
    return render_template(
        "reading_list.html",
        books=books,
        reading_statuses=READING_STATUSES,
        status_filter=status_filter,
        current_page="reading_list",
    )


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = get_current_user()
    if request.method == "POST":
        if not csrf_ok():
            flash("The form expired. Please try again.", "warning")
            return redirect(url_for("profile"))
        email = request.form.get("email", "").strip().lower()
        if not EMAIL_PATTERN.fullmatch(email):
            flash("Please enter a valid email address.", "danger")
            return render_template("profile.html", form={"email": email}, current_page="profile")
        try:
            execute_query(
                "UPDATE users SET email = %s WHERE id = %s",
                (email, user["id"]),
            )
            flash("Your profile was updated.", "success")
            return redirect(url_for("profile"))
        except IntegrityError:
            flash("That email is already in use.", "danger")
        except Error as error:
            app.logger.exception("Profile update error: %s", error)
            flash("Could not update your profile.", "danger")
        return render_template("profile.html", form={"email": email}, current_page="profile")
    return render_template(
        "profile.html",
        form={"email": user["email"]},
        current_page="profile",
    )


@app.route("/uploads/<path:filename>")
def uploaded_cover(filename):
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != Path(filename).name:
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, safe_name)


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
                SELECT id, username, email, password_hash, role, is_active
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
        if not user.get("is_active", 1):
            flash("This account has been deactivated.", "danger")
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
    try:
        books = fetch_all(
            BOOKS_WITH_STATS + " ORDER BY b.created_at DESC"
        )
        pending = fetch_all(
            """
            SELECT r.id, r.rating, r.review_text, r.is_spoiler, r.created_at,
                   u.username, b.id AS book_id, b.title
            FROM reviews r
            JOIN users u ON u.id = r.user_id
            JOIN books b ON b.id = r.book_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at ASC
            """
        )
        stats = fetch_one(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS user_count,
                (SELECT COUNT(*) FROM books) AS book_count,
                (SELECT COUNT(*) FROM reviews) AS review_count,
                (SELECT AVG(rating) FROM reviews WHERE status = 'approved') AS avg_rating
            """
        )
        user_search = request.args.get("user_q", "").strip()
        user_sql = """
            SELECT id, username, email, role, is_active, created_at
            FROM users
        """
        user_params = []
        if user_search:
            user_sql += " WHERE username LIKE %s OR email LIKE %s"
            like = f"%{user_search}%"
            user_params.extend([like, like])
        user_sql += " ORDER BY created_at DESC"
        users = fetch_all(user_sql, tuple(user_params))
    except Error as error:
        app.logger.exception("Admin dashboard error: %s", error)
        flash("Could not load admin data.", "danger")
        books, pending, stats, users, user_search = [], [], {}, [], ""
    return render_template(
        "admin.html",
        books=[decorate_book(book) for book in books],
        pending_reviews=pending,
        users=users,
        user_search=user_search,
        stats=stats or {},
        avg_rating_display=format_rating((stats or {}).get("avg_rating")),
        current_page="admin",
    )


@app.route("/admin/books/new", methods=["GET", "POST"])
@admin_required
def admin_new_book():
    form = empty_book_form()
    if request.method == "POST":
        if not csrf_ok():
            flash("The form expired. Please try again.", "warning")
            return redirect(url_for("admin_new_book"))
        form = {key: request.form.get(key, "") for key in empty_book_form()}
        data, error = validate_book_form(form)
        if error:
            flash(error, "danger")
            return render_template(
                "admin_book_form.html", form=form, mode="new", current_page="admin"
            )
        filename, file_error = save_cover_file(request.files.get("cover_file"))
        if file_error:
            flash(file_error, "danger")
            return render_template(
                "admin_book_form.html", form=form, mode="new", current_page="admin"
            )
        try:
            execute_query(
                """
                INSERT INTO books
                    (title, author, genre, cover_url, cover_filename, description,
                     isbn, publisher, publication_year)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    data["title"], data["author"], data["genre"], data["cover_url"],
                    filename, data["description"], data["isbn"], data["publisher"],
                    data["publication_year"],
                ),
            )
            flash("Book added to the catalogue.", "success")
            return redirect(url_for("admin_dashboard"))
        except Error as error:
            delete_cover_file(filename)
            app.logger.exception("Add book error: %s", error)
            flash("Could not save the book.", "danger")
    return render_template(
        "admin_book_form.html", form=form, mode="new", current_page="admin"
    )


@app.route("/admin/books/<int:book_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_book(book_id):
    book = fetch_one("SELECT * FROM books WHERE id = %s", (book_id,))
    if not book:
        abort(404)
    form = book_to_form(book)
    if request.method == "POST":
        if not csrf_ok():
            flash("The form expired. Please try again.", "warning")
            return redirect(url_for("admin_edit_book", book_id=book_id))
        form = {key: request.form.get(key, "") for key in empty_book_form()}
        data, error = validate_book_form(form)
        if error:
            flash(error, "danger")
            return render_template(
                "admin_book_form.html",
                form=form,
                mode="edit",
                book=book,
                current_page="admin",
            )
        filename, file_error = save_cover_file(request.files.get("cover_file"))
        if file_error:
            flash(file_error, "danger")
            return render_template(
                "admin_book_form.html",
                form=form,
                mode="edit",
                book=book,
                current_page="admin",
            )
        cover_filename = filename or book.get("cover_filename")
        try:
            execute_query(
                """
                UPDATE books
                SET title = %s, author = %s, genre = %s, cover_url = %s,
                    cover_filename = %s, description = %s, isbn = %s,
                    publisher = %s, publication_year = %s
                WHERE id = %s
                """,
                (
                    data["title"], data["author"], data["genre"], data["cover_url"],
                    cover_filename, data["description"], data["isbn"],
                    data["publisher"], data["publication_year"], book_id,
                ),
            )
            if filename and book.get("cover_filename"):
                delete_cover_file(book["cover_filename"])
            flash("Book details were updated.", "success")
            return redirect(url_for("admin_dashboard"))
        except Error as error:
            delete_cover_file(filename)
            app.logger.exception("Edit book error: %s", error)
            flash("Could not update the book.", "danger")
    return render_template(
        "admin_book_form.html",
        form=form,
        mode="edit",
        book=book,
        current_page="admin",
    )


@app.route("/admin/books/<int:book_id>/delete", methods=["POST"])
@admin_required
def admin_delete_book(book_id):
    if not csrf_ok():
        flash("The form expired. Please try again.", "warning")
        return redirect(url_for("admin_dashboard"))
    book = fetch_one("SELECT id, cover_filename FROM books WHERE id = %s", (book_id,))
    if not book:
        abort(404)
    try:
        execute_query("DELETE FROM books WHERE id = %s", (book_id,))
        delete_cover_file(book.get("cover_filename"))
        flash("Book deleted.", "success")
    except Error as error:
        app.logger.exception("Delete book error: %s", error)
        flash("Could not delete the book.", "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reviews/<int:review_id>/moderate", methods=["POST"])
@admin_required
def admin_moderate_review(review_id):
    if not csrf_ok():
        flash("The form expired. Please try again.", "warning")
        return redirect(url_for("admin_dashboard"))
    review = fetch_one("SELECT id FROM reviews WHERE id = %s", (review_id,))
    if not review:
        abort(404)
    action = request.form.get("action")
    if action not in {"approved", "rejected"}:
        flash("Choose approve or reject.", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        execute_query(
            "UPDATE reviews SET status = %s WHERE id = %s",
            (action, review_id),
        )
        flash(f"Review {action}.", "success")
    except Error as error:
        app.logger.exception("Moderation error: %s", error)
        flash("Could not update the review.", "danger")
    return redirect(url_for("admin_dashboard"))


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
