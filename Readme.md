# OpenShelf — Online Book Review System

A straightforward Flask + MySQL book discovery and review website for college submission and portfolio use.

## Feature checklist

| Feature | Status |
| --- | --- |
| Project skeleton and homepage layout | Implemented (Stage 1) |
| Database connection and authentication | Pending (Stage 2) |
| Book catalogue, search, filters, pagination | Pending (Stage 3) |
| Reviews, ratings and moderation | Pending (Stage 4) |
| Reading list, comments and votes | Pending (Stage 5) |
| Recommendations and admin dashboard | Pending (Stage 6) |
| Final end-to-end testing | Pending (Stage 7) |

## Stage 1 notes

The homepage uses labelled sample book cards so the layout can be reviewed. Those cards are **not** loaded from MySQL yet.

Login, register, reviews, reading list, profile and admin pages are shown in the navigation for layout, but they currently return to the homepage until their stages are built.

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

4. Copy the example environment file and edit it with your own values:

```powershell
copy .env.example .env
```

MySQL is **not required** to view the Stage 1 homepage.

5. Run the app:

```powershell
python app.py
```

6. Open http://127.0.0.1:5000 in a browser.

## Database (used from Stage 2)

1. Install and start MySQL.
2. Create a database user or use your local root account.
3. Fill in `.env` using `.env.example` as a guide. Do not put real passwords in source files.
4. Run `schema.sql` in MySQL when you are ready to create tables:

```powershell
mysql -u root -p < schema.sql
```

Or open MySQL Workbench / the MySQL command line and execute the contents of `schema.sql`.

## Project files

- `app.py` — Flask app and routes
- `db.py` — MySQL connection helpers
- `schema.sql` — database tables
- `templates/` — HTML pages
- `static/` — CSS, JavaScript and images
- `uploads/` — book cover uploads (later stages)
