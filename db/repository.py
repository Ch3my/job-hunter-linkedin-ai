"""Persistencia SQLite. Mismo archivo y mismo esquema de siempre (`jobs.db`).

Cada funcion abre y cierra su propia conexion: asi se puede llamar desde el
thread de la UI o desde el thread de busqueda sin el error
"SQLite objects created in a thread can only be used in that same thread".
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from identity import build_job_key
from models import APPLIED, DISCARDED, NOT_APPLIED, JobPosting
from utils import append_to_log, log_exception

DB_FILE = "jobs.db"


@contextmanager
def connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=True)
    try:
        yield conn
    finally:
        conn.close()


SCHEMA = """
    CREATE TABLE IF NOT EXISTS jobs (
        job_key TEXT PRIMARY KEY,
        title TEXT,
        company TEXT,
        description TEXT,
        joburl TEXT,
        applied TEXT,
        createdAt TEXT,
        relevant TEXT,
        score INTEGER,
        reason TEXT
    )
"""

# Los descartados por la AI tambien se guardan, para no volver a pagarle al LLM
# por el mismo trabajo en cada corrida. No son candidatos, asi que se excluyen
# de la grilla y de las estadisticas con esta condicion.
NOT_DISCARDED_BY_AI = "COALESCE(relevant, '') != 'no-relevante'"


def create_table() -> bool:
    try:
        with connect() as conn:
            _migrate(conn)
            conn.execute(SCHEMA)
            _add_missing_columns(conn)
            conn.commit()
        return True
    except sqlite3.Error as error:
        log_exception("create_table", error)
        return False


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Agrega las columnas del veredicto de la AI a una tabla ya existente.

    `CREATE TABLE IF NOT EXISTS` no toca una tabla que ya esta, asi que las
    columnas nuevas hay que agregarlas a mano. Las filas viejas quedan con NULL,
    que es justo lo que `NOT_DISCARDED_BY_AI` trata como "no descartado": un
    trabajo guardado antes de esto sigue apareciendo en la grilla.
    """
    columnas = [c[1] for c in conn.execute("PRAGMA table_info(jobs)")]
    for nombre, tipo in (("relevant", "TEXT"), ("score", "INTEGER"), ("reason", "TEXT")):
        if nombre not in columnas:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {nombre} {tipo}")


def _migrate(conn: sqlite3.Connection) -> None:
    """Lleva una tabla vieja (PK title+company exactos) al esquema con job_key.

    La version anterior comparaba los textos tal cual, asi que dejaba entrar
    duplicados por mayusculas, acentos o sufijos como "(H/F)". Al migrar se
    recalcula la clave normalizada; si dos filas antiguas colapsan en la misma
    clave se conserva la que ya tenia una decision tomada (Applied/Discarded).
    """
    tabla = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone()
    if not tabla:
        return

    columnas = [c[1] for c in conn.execute("PRAGMA table_info(jobs)")]
    if "job_key" in columnas:
        return  # ya migrada

    filas = conn.execute(
        "SELECT title, company, description, joburl, applied, createdAt FROM jobs"
    ).fetchall()

    # Prioridad al elegir sobrevivientes: una decision tomada vale mas que el default.
    prioridad = {APPLIED: 2, DISCARDED: 2, NOT_APPLIED: 1}
    mejores = {}
    for title, company, description, joburl, applied, created in filas:
        key = build_job_key(title or "", company or "")
        actual = mejores.get(key)
        if actual is None or prioridad.get(applied, 0) > prioridad.get(actual[4], 0):
            mejores[key] = (title, company, description, joburl, applied, created)

    conn.execute("ALTER TABLE jobs RENAME TO jobs_v1")
    conn.execute(SCHEMA)
    conn.executemany(
        """
        INSERT INTO jobs (job_key, title, company, description, joburl, applied, createdAt)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(key, *valores) for key, valores in mejores.items()],
    )
    conn.execute("DROP TABLE jobs_v1")
    conn.commit()

    colapsadas = len(filas) - len(mejores)
    append_to_log(
        f"[db] migrada a clave normalizada: {len(mejores)} trabajos"
        + (f", {colapsadas} duplicados fusionados" if colapsadas else "")
    )


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
    """Se usa antes de llamar a la AI, para no gastar tokens en trabajos ya evaluados.

    A proposito NO filtra por `relevant`: un trabajo que la AI ya descarto
    tambien "existe", y volver a mandarlo al LLM seria pagar dos veces por la
    misma respuesta.
    """
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE job_key=?", (build_job_key(title, company),)
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
                INSERT INTO jobs (job_key, title, company, description, joburl, applied,
                                  createdAt, relevant, score, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    posting.key,
                    posting.title,
                    posting.company,
                    posting.description_for_storage(),
                    posting.url,
                    posting.applied or NOT_APPLIED,
                    created_at,
                    posting.relevant,
                    posting.score,
                    posting.reason,
                ),
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # ya estaba guardado (misma clave normalizada)
    except sqlite3.Error as error:
        log_exception(f"insert_job({posting.title} @ {posting.company})", error)
        return False


def update_job_status(new_status: str, title: str, company: str) -> bool:
    try:
        with connect() as conn:
            conn.execute(
                "UPDATE jobs SET applied=? WHERE job_key=?",
                (new_status, build_job_key(title, company)),
            )
            conn.commit()
        return True
    except sqlite3.Error as error:
        log_exception("update_job_status", error)
        return False


def select_jobs() -> List[Tuple]:
    """Filas para la grilla: (title, company, applied, createdAt, score).

    Solo candidatos; los descartados por la AI quedan guardados pero fuera.
    """
    try:
        with connect() as conn:
            return conn.execute(
                f"""
                SELECT title, company, applied, createdAt, CASE WHEN COALESCE(score, -1) < 0 THEN '' ELSE score END
                FROM jobs WHERE {NOT_DISCARDED_BY_AI} ORDER BY createdAt DESC
                """
            ).fetchall()
    except sqlite3.Error as error:
        log_exception("select_jobs", error)
        return []


def select_discarded_jobs() -> List[Tuple]:
    """Lo que la AI descarto, con su puntaje y motivo.

    No lo usa la UI todavia; sirve para revisar por que se esta filtrando algo
    y ajustar prompt.txt (o el minScore) con datos en vez de a ciegas.
    """
    try:
        with connect() as conn:
            return conn.execute(
                """
                SELECT title, company, CASE WHEN COALESCE(score, -1) < 0 THEN '' ELSE score END, COALESCE(reason, ''), createdAt
                FROM jobs WHERE relevant = 'no-relevante' ORDER BY createdAt DESC
                """
            ).fetchall()
    except sqlite3.Error as error:
        log_exception("select_discarded_jobs", error)
        return []


def select_one_job(title: str, company: str) -> Optional[Tuple]:
    """Devuelve (description, joburl, reason) o None."""
    try:
        with connect() as conn:
            return conn.execute(
                "SELECT description, joburl, COALESCE(reason, '') FROM jobs WHERE job_key=?",
                (build_job_key(title, company),),
            ).fetchone()
    except sqlite3.Error as error:
        log_exception("select_one_job", error)
        return None


def delete_job(title: str, company: str) -> int:
    try:
        with connect() as conn:
            cursor = conn.execute(
                "DELETE FROM jobs WHERE job_key=?", (build_job_key(title, company),)
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
            # Mismo criterio que la grilla: se cuentan candidatos, no descartes
            # de la AI. Si no, "Total" no coincidiria con lo que se ve en pantalla.
            stats["total"] = conn.execute(
                f"SELECT COUNT(*) FROM jobs WHERE {NOT_DISCARDED_BY_AI}"
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT applied, COUNT(*) FROM jobs WHERE {NOT_DISCARDED_BY_AI} GROUP BY applied"
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
