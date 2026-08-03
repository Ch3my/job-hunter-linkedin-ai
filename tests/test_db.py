"""SQLite: el esquema no cambia y los errores no se propagan."""

import sqlite3

import pytest

from db import (
    check_table_exists,
    create_table,
    delete_job,
    get_jobs_stats,
    insert_job,
    job_exists,
    select_jobs,
    select_one_job,
    truncate_table,
    update_job_status,
)
from models import APPLIED, DISCARDED, NOT_APPLIED, JobPosting, make_manual_posting

# job_key se agrego al pasar a la clave normalizada; el resto de las columnas
# es identico a la version anterior, para no perder los datos ya guardados.
COLUMNAS = ["job_key", "title", "company", "description", "joburl", "applied", "createdAt"]


@pytest.fixture
def tabla():
    create_table()


def trabajo(title="Contador", company="ACME", **kw):
    return JobPosting(title=title, company=company, **kw)


class TestEsquema:
    def test_columnas(self, tabla, workdir):
        with sqlite3.connect(workdir / "jobs.db") as conn:
            columnas = [c[1] for c in conn.execute("PRAGMA table_info(jobs)")]
        assert columnas == COLUMNAS

    def test_las_columnas_de_datos_no_cambiaron(self, tabla, workdir):
        """Los datos que ya tenias se siguen guardando igual."""
        with sqlite3.connect(workdir / "jobs.db") as conn:
            columnas = [c[1] for c in conn.execute("PRAGMA table_info(jobs)")]
        assert columnas[1:] == ["title", "company", "description", "joburl", "applied", "createdAt"]

    def test_clave_primaria_es_job_key(self, tabla, workdir):
        with sqlite3.connect(workdir / "jobs.db") as conn:
            pk = [c[1] for c in conn.execute("PRAGMA table_info(jobs)") if c[5]]
        assert pk == ["job_key"]

    def test_create_table_es_idempotente(self):
        assert create_table() and create_table()

    def test_check_table_exists(self):
        assert check_table_exists() is False
        create_table()
        assert check_table_exists() is True


class TestInsert:
    def test_inserta(self, tabla):
        assert insert_job(trabajo()) is True
        assert len(select_jobs()) == 1

    def test_no_duplica(self, tabla):
        assert insert_job(trabajo()) is True
        assert insert_job(trabajo()) is False
        assert len(select_jobs()) == 1

    @pytest.mark.parametrize("title,company", [("", "ACME"), ("T", ""), ("", ""), ("  ", "  ")])
    def test_rechaza_sin_clave(self, tabla, title, company):
        assert insert_job(JobPosting(title=title, company=company)) is False

    def test_guarda_resumen_cuando_no_hay_descripcion(self, tabla):
        insert_job(trabajo(location="Santiago", employment_type="FULL_TIME"))
        descripcion = select_one_job("Contador", "ACME")[0]
        assert "no entrego descripcion" in descripcion
        assert "Santiago" in descripcion

    def test_estado_por_defecto(self, tabla):
        insert_job(trabajo())
        assert select_jobs()[0][2] == NOT_APPLIED


class TestConsultas:
    def test_job_exists(self, tabla):
        assert job_exists("Contador", "ACME") is False
        insert_job(trabajo())
        assert job_exists("Contador", "ACME") is True

    def test_select_one_job_devuelve_descripcion_y_url(self, tabla):
        insert_job(trabajo(description="una descripcion", url="http://x"))
        assert select_one_job("Contador", "ACME") == ("una descripcion", "http://x")

    def test_select_one_job_inexistente(self, tabla):
        assert select_one_job("no", "existe") is None

    def test_orden_por_fecha_descendente(self, tabla):
        insert_job(trabajo(title="A"))
        insert_job(trabajo(title="B"))
        assert len(select_jobs()) == 2

    def test_columnas_de_la_grilla(self, tabla):
        insert_job(trabajo())
        assert len(select_jobs()[0]) == 4


class TestEstadoYBorrado:
    def test_actualiza_estado(self, tabla):
        insert_job(trabajo())
        assert update_job_status(APPLIED, "Contador", "ACME") is True
        assert select_jobs()[0][2] == APPLIED

    def test_borra(self, tabla):
        insert_job(trabajo())
        assert delete_job("Contador", "ACME") == 1
        assert select_jobs() == []

    def test_borrar_inexistente_devuelve_cero(self, tabla):
        assert delete_job("no", "existe") == 0

    def test_truncate(self, tabla):
        insert_job(trabajo())
        exito, mensaje = truncate_table()
        assert exito and "exitosamente" in mensaje
        assert select_jobs() == []


class TestEstadisticas:
    def test_cuenta_por_estado(self, tabla):
        insert_job(trabajo(title="A"))
        insert_job(trabajo(title="B", applied=APPLIED))
        insert_job(trabajo(title="C", applied=DISCARDED))
        assert get_jobs_stats() == {"total": 3, "applied": 1, "discarded": 1, "not_applied": 1}

    def test_tabla_vacia(self, tabla):
        assert get_jobs_stats()["total"] == 0


class TestErroresNoPropagan:
    """Sin tabla, todo devuelve un valor por defecto en vez de lanzar."""

    def test_sin_tabla_no_lanza(self):
        assert select_jobs() == []
        assert select_one_job("a", "b") is None
        assert job_exists("a", "b") is False
        assert delete_job("a", "b") == 0
        assert insert_job(trabajo()) is False
        assert get_jobs_stats()["total"] == 0
        assert truncate_table()[0] is False


class TestCargaManualDesdeLaUI:
    def test_make_manual_posting(self, tabla):
        job = make_manual_posting("Cargo", "Empresa", "http://u", "desc", APPLIED)
        assert job.source == "manual"
        assert insert_job(job) is True
        assert select_jobs()[0][2] == APPLIED

    def test_estado_invalido_cae_a_not_applied(self):
        assert make_manual_posting("C", "E", applied="loquesea").applied == NOT_APPLIED
