"""Simple MySQL helpers used by the whole application."""

import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv
from mysql.connector import Error

load_dotenv()

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _base_config():
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
    }


def get_server_connection():
    """Connect to MySQL without selecting a database (used to create it)."""
    return mysql.connector.connect(**_base_config())


def get_connection():
    """Open a new MySQL connection using values from the environment."""
    config = _base_config()
    config["database"] = os.getenv("DB_NAME", "book_review_system")
    return mysql.connector.connect(**config)


def fetch_all(sql, params=None):
    """Run a SELECT query and return a list of rows as dictionaries."""
    connection = get_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql, params or ())
        rows = cursor.fetchall()
        cursor.close()
        return rows
    finally:
        connection.close()


def fetch_one(sql, params=None):
    """Run a SELECT query and return one row, or None."""
    connection = get_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql, params or ())
        row = cursor.fetchone()
        cursor.close()
        return row
    finally:
        connection.close()


def execute_query(sql, params=None):
    """Run INSERT/UPDATE/DELETE and commit the change."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(sql, params or ())
        connection.commit()
        last_id = cursor.lastrowid
        cursor.close()
        return last_id
    except Error:
        connection.rollback()
        raise
    finally:
        connection.close()


def apply_schema():
    """Create the database and tables from schema.sql without dropping data."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = get_server_connection()
    try:
        cursor = connection.cursor()
        for _result in cursor.execute(sql, multi=True):
            pass
        connection.commit()
        cursor.close()
    except Error:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_tables():
    """Return table names in the application database."""
    rows = fetch_all("SHOW TABLES")
    names = []
    for row in rows:
        names.extend(row.values())
    return names
