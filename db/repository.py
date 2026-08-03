"""Persistencia SQLite. Mismo archivo y mismo esquema de siempre (`jobs.db`).

Cada funcion abre y cierra su propia conexion: asi se puede llamar desde el
thread de la UI o desde el thread de busqueda sin el error
"SQLite objects created in a thread can only be used in that same thread".
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from models import APPLIED, DISCARDED, NOT_APPLIED, JobPosting
from utils import log_exception

DB_FILE = "jobs.db"


@contextmanager
def connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=True)
    try:
        yield conn
    finally:
        conn.close()


def create_table() -> bool:
    try:
        with connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    title TEXT,
                    company TEXT,
                    description TEXT,
                    joburl TEXT,
                    applied TEXT,
                    createdAt TEXT,
                    PRIMARY KEY (title, company)
                )
                """
            )
            conn.commit()
        return True
    except sqlite3.Error as error:
        log_exception("create_table", error)
        return False


def check_table_exists() -> bool:
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone()
        return row is not None
    except sqlite3.Error as error:
        log_exception("check_table_exists", error)
        return False


def job_exists(title: str, company: str) -> bool:
    """Se usa antes de llamar a la AI, para no gastar tokens en trabajos ya guardados."""
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE title=? AND company=?", (title, company)
            ).fetchone()
        return row is not None
    except sqlite3.Error as error:
        log_exception("job_exists", error)
        return False


def insert_job(posting: JobPosting) -> bool:
    """Inserta un trabajo. Devuelve False si ya existia o si hubo un error."""
    if not posting.is_valid():
        return False

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (title, company, description, joburl, applied, createdAt)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    posting.title,
                    posting.company,
                    posting.description_for_storage(),
                    posting.url,
                    posting.applied or NOT_APPLIED,
                    created_at,
                ),
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # ya estaba guardado (PK titulo + empresa)
    except sqlite3.Error as error:
        log_exception(f"insert_job({posting.title} @ {posting.company})", error)
        return False


def update_job_status(new_status: str, title: str, company: str) -> bool:
    try:
        with connect() as conn:
            conn.execute(
                "UPDATE jobs SET applied=? WHERE title=? AND company=?",
                (new_status, title, company),
            )
            conn.commit()
        return True
    except sqlite3.Error as error:
        log_exception("update_job_status", error)
        return False


def select_jobs() -> List[Tuple]:
    try:
        with connect() as conn:
            return conn.execute(
                "SELECT title, company, applied, createdAt FROM jobs ORDER BY createdAt DESC"
            ).fetchall()
    except sqlite3.Error as error:
        log_exception("select_jobs", error)
        return []


def select_one_job(title: str, company: str) -> Optional[Tuple]:
    """Devuelve (description, joburl) o None."""
    try:
        with connect() as conn:
            return conn.execute(
                "SELECT description, joburl FROM jobs WHERE title=? AND company=?",
                (title, company),
            ).fetchone()
    except sqlite3.Error as error:
        log_exception("select_one_job", error)
        return None


def delete_job(title: str, company: str) -> int:
    try:
        with connect() as conn:
            cursor = conn.execute(
                "DELETE FROM jobs WHERE title=? AND company=?", (title, company)
            )
            conn.commit()
            return cursor.rowcount
    except sqlite3.Error as error:
        log_exception("delete_job", error)
        return 0


def truncate_table() -> Tuple[bool, str]:
    try:
        with connect() as conn:
            conn.execute("DELETE FROM jobs")
            conn.commit()
        return True, "La tabla de trabajos ha sido vaciada exitosamente."
    except sqlite3.Error as error:
        log_exception("truncate_table", error)
        return False, f"Ocurrio un error al vaciar la tabla de trabajos: {error}"


def get_jobs_stats() -> Dict[str, int]:
    stats = {"total": 0, "applied": 0, "discarded": 0, "not_applied": 0}
    try:
        with connect() as conn:
            stats["total"] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            rows = conn.execute(
                "SELECT applied, COUNT(*) FROM jobs GROUP BY applied"
            ).fetchall()
    except sqlite3.Error as error:
        log_exception("get_jobs_stats", error)
        return stats

    buckets = {APPLIED: "applied", DISCARDED: "discarded", NOT_APPLIED: "not_applied"}
    for status, count in rows:
        key = buckets.get(status)
        if key:
            stats[key] = count

    return stats
