"""Persistencia de la aplicacion."""

from db.repository import (
    check_table_exists,
    create_table,
    delete_job,
    get_jobs_stats,
    insert_job,
    job_exists,
    select_discarded_jobs,
    select_jobs,
    select_one_job,
    truncate_table,
    update_job_status,
)

__all__ = [
    "check_table_exists",
    "create_table",
    "delete_job",
    "get_jobs_stats",
    "insert_job",
    "job_exists",
    "select_discarded_jobs",
    "select_jobs",
    "select_one_job",
    "truncate_table",
    "update_job_status",
]
