# OpenShelf — Online Book Review System

A straightforward Flask + MySQL book discovery and review website for college submission and portfolio use.

## Feature checklist

| Feature | Status |
| --- | --- |
| Project skeleton and homepage layout | Implemented |
| Database connection and authentication | Implemented |
| Book catalogue, search, filters, pagination | Implemented |
| Book details, reviews, ratings and moderation | Implemented |
| My Reviews, reading list and editable reader profile | Implemented |
| Admin book management | Implemented |
| Comments, helpful votes and recommendations | Pending |

## Setup (Windows PowerShell)

1. Open PowerShell in the project folder.
2. Create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks scripts, run this once for your user account, then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

3. Install packages:

```powershell
pip install -r requirements.txt
```

4. Copy the example environment file and edit it with your own values. Generate a unique secret with `python -c "import secrets; print(secrets.token_hex(32))"` and set it as `FLASK_SECRET_KEY`. Do not use the example placeholder or commit `.env`.

```powershell
copy .env.example .env
```

`APP_ENV` must be `development` for local work or `production` on the hosting platform. OpenShelf will not start if `FLASK_SECRET_KEY` is missing. In production, session cookies are marked Secure, HttpOnly, and SameSite=Lax.

5. Create or update the database tables (safe to re-run; it does not drop existing data):

```powershell
python init_db.py
```

The setup applies only additive profile columns for display name, bio, favourite genres and books, reading goal, and profile-picture filename. Existing accounts, reviews, books and uploaded covers are preserved.

6. Create the first administrator (public registration cannot do this):

```powershell
python create_admin.py shelfadmin admin@example.com ChangeMe123
```

7. Run the local development server:

```powershell
python app.py
```

8. Open http://127.0.0.1:5000 in a browser.

## Production startup

The `Procfile` starts the app with Gunicorn on the hosting platform's `$PORT`. Configure `APP_ENV=production` and a unique `FLASK_SECRET_KEY` in the platform's environment/secrets settings; do not upload `.env`. The same production command can be run on a Linux host with `gunicorn --bind 0.0.0.0:$PORT app:app`. Keep `python app.py` for local development.

## Adding books

If the catalogue is empty, log in as an administrator, open **Admin Dashboard**, and use **Add a book**. Normal users cannot create books.

New reviews stay **pending** until an administrator approves them. Only approved reviews appear on book pages and in public average ratings.

## Project files

- `app.py` — Flask routes
- `db.py` — MySQL connection helpers
- `schema.sql` — database tables
- `init_db.py` — applies the schema without dropping data
- `create_admin.py` — creates the first admin account
- `templates/` — HTML pages
- `static/` — CSS, JavaScript and images
- `uploads/` — locally uploaded book covers and profile pictures
