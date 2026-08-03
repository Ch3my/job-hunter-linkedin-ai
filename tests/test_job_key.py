"""La clave normalizada: cargo + empresa, comparados sin ruido de formato."""

import sqlite3

import pytest

from db import create_table, insert_job, job_exists, select_jobs, select_one_job, update_job_status
from identity import build_job_key, normalize_key_part
from models import APPLIED, DISCARDED, NOT_APPLIED, JobPosting


class TestNormalizacion:
    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("Nutricionista", "nutricionista"),
            ("NUTRICIONISTA", "nutricionista"),
            ("  Nutricionista  ", "nutricionista"),
            ("Nutricionista (H/F)", "nutricionista"),
            ("Nutricionista (M/W/D)", "nutricionista"),
            ("Contador   Auditor", "contador auditor"),
            ("Analista de Nutrición", "analista de nutricion"),
            ("Ingeniero/a Senior", "ingeniero a senior"),
            ("Chef - Jefe de Cocina", "chef jefe de cocina"),
            ("Bulk™", "bulk"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normaliza(self, texto, esperado):
        assert normalize_key_part(texto) == esperado

    def test_acentos_no_generan_claves_distintas(self):
        assert normalize_key_part("Nutrición") == normalize_key_part("Nutricion")

    def test_no_junta_palabras_distintas(self):
        assert normalize_key_part("Contador") != normalize_key_part("Contadora")
        assert normalize_key_part("Chef") != normalize_key_part("Chief")


class TestNoSePierdeSignificado:
    """Normalizar es quitar ruido de formato, nunca contenido."""

    def test_lenguajes_con_simbolos_siguen_siendo_distintos(self):
        claves = {normalize_key_part(t) for t in ("C++ Developer", "C# Developer", "C Developer")}
        assert len(claves) == 3, claves

    @pytest.mark.parametrize(
        "texto,esperado",
        [("C++ Developer", "c++ developer"), ("C# Developer", "c# developer")],
    )
    def test_conserva_los_simbolos_significativos(self, texto, esperado):
        assert normalize_key_part(texto) == esperado

    @pytest.mark.parametrize(
        "a,b",
        [
            ("Aramark S.A.", "Aramark SA"),
            ("L'Oreal", "LOreal"),
            (".NET Developer", "NET Developer"),
        ],
    )
    def test_los_puntos_y_apostrofes_no_separan(self, a, b):
        """'S.A.' y 'SA' son la misma empresa."""
        assert normalize_key_part(a) == normalize_key_part(b)

    def test_los_parentesis_con_informacion_se_respetan(self):
        """Solo se quitan los sufijos de genero, no cualquier parentesis."""
        assert normalize_key_part("Chef (Remote)") != normalize_key_part("Chef")
        assert normalize_key_part("Nutricionista (Turno Noche)") != normalize_key_part("Nutricionista")


class TestBuildJobKey:
    def test_formato(self):
        assert build_job_key("Nutricionista", "Aramark") == "nutricionista|aramark"

    @pytest.mark.parametrize(
        "title,company",
        [
            ("Nutricionista", "Aramark Chile"),
            ("NUTRICIONISTA", "ARAMARK CHILE"),
            ("Nutricionista (H/F)", "Aramark Chile"),
            ("  Nutricionista ", "Aramark  Chile"),
            ("Nutricionista", "Aramark Chile."),
        ],
    )
    def test_todas_las_variantes_dan_la_misma_clave(self, title, company):
        assert build_job_key(title, company) == build_job_key("Nutricionista", "Aramark Chile")

    def test_empresas_distintas_dan_claves_distintas(self):
        assert build_job_key("Nutricionista", "Aramark") != build_job_key("Nutricionista", "Sodexo")

    def test_la_clave_no_depende_del_proveedor(self):
        """El mismo trabajo visto por dos APIs distintas debe dar UNA sola fila.

        Cada adapter extrae el titulo y la empresa de su propio JSON, pero la
        identidad se calcula igual para todos.
        """
        from providers.fantastic_linkedin import to_posting as v4
        from providers.linkedin_data_scraper import to_posting as legacy

        desde_v4 = v4({"title": "Nutricionista (H/F)", "organization": "Aramark Chile"})
        desde_legacy = legacy({"title": "NUTRICIONISTA", "companyName": "aramark chile"})

        assert desde_v4.source != desde_legacy.source     # vienen de APIs distintas
        assert desde_v4.key == desde_legacy.key           # pero son el mismo trabajo

    def test_la_propiedad_key_del_modelo_usa_lo_mismo(self):
        job = JobPosting(title="Nutricionista (H/F)", company="Aramark Chile")
        assert job.key == build_job_key("Nutricionista", "Aramark Chile")


class TestDeduplicacionReal:
    """El caso concreto que motivo el cambio."""

    @pytest.fixture(autouse=True)
    def tabla(self):
        create_table()

    def test_las_variantes_de_titulo_ya_no_se_cuelan(self):
        variantes = [
            JobPosting(title="Nutricionista", company="Aramark Chile"),
            JobPosting(title="Nutricionista (H/F)", company="Aramark Chile"),
            JobPosting(title="nutricionista", company="aramark chile"),
            JobPosting(title="Nutricionista ", company="Aramark Chile"),
            JobPosting(title="NUTRICIONISTA", company="ARAMARK CHILE"),
        ]
        guardados = [insert_job(job) for job in variantes]
        assert guardados == [True, False, False, False, False]
        assert len(select_jobs()) == 1

    def test_se_conserva_el_texto_original_para_mostrar(self):
        """La clave se normaliza, pero en pantalla se ve lo que trajo la API."""
        insert_job(JobPosting(title="Nutricionista (H/F)", company="Aramark Chile"))
        titulo, empresa, _, _ = select_jobs()[0]
        assert titulo == "Nutricionista (H/F)"
        assert empresa == "Aramark Chile"

    def test_trabajos_distintos_siguen_entrando(self):
        assert insert_job(JobPosting(title="Nutricionista", company="Aramark"))
        assert insert_job(JobPosting(title="Nutricionista Jefe", company="Aramark"))
        assert insert_job(JobPosting(title="Nutricionista", company="Sodexo"))
        assert len(select_jobs()) == 3


class TestBusquedasPorClave:
    """La UI sigue pasando (title, company): el round-trip tiene que funcionar."""

    @pytest.fixture(autouse=True)
    def tabla(self):
        create_table()
        insert_job(JobPosting(title="Nutricionista (H/F)", company="Aramark Chile",
                              description="desc", url="http://u"))

    def test_job_exists_con_el_texto_guardado(self):
        assert job_exists("Nutricionista (H/F)", "Aramark Chile") is True

    def test_job_exists_con_una_variante(self):
        assert job_exists("nutricionista", "ARAMARK CHILE") is True

    def test_select_one_job_con_el_texto_guardado(self):
        assert select_one_job("Nutricionista (H/F)", "Aramark Chile") == ("desc", "http://u")

    def test_update_status_con_el_texto_guardado(self):
        assert update_job_status(APPLIED, "Nutricionista (H/F)", "Aramark Chile")
        assert select_jobs()[0][2] == APPLIED

    def test_no_encuentra_otro_trabajo(self):
        assert job_exists("Nutricionista", "Sodexo") is False


class TestMigracionDesdeElEsquemaViejo:
    """Una jobs.db de la version anterior tiene que seguir funcionando."""

    @pytest.fixture
    def db_vieja(self, workdir):
        def _crear(filas):
            with sqlite3.connect(workdir / "jobs.db") as conn:
                conn.execute("""
                    CREATE TABLE jobs (
                        title TEXT, company TEXT, description TEXT,
                        joburl TEXT, applied TEXT, createdAt TEXT,
                        PRIMARY KEY (title, company)
                    )
                """)
                conn.executemany(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)", filas)
                conn.commit()

        return _crear

    def test_migra_conservando_los_datos(self, db_vieja, workdir):
        db_vieja([("Nutricionista", "Aramark", "desc", "http://u", APPLIED, "2026-01-01 10:00:00")])
        assert create_table()

        columnas = [c[1] for c in sqlite3.connect(workdir / "jobs.db").execute("PRAGMA table_info(jobs)")]
        assert columnas[0] == "job_key"

        filas = select_jobs()
        assert len(filas) == 1
        assert filas[0][0] == "Nutricionista"
        assert filas[0][2] == APPLIED
        assert select_one_job("Nutricionista", "Aramark") == ("desc", "http://u")

    def test_fusiona_los_duplicados_que_se_habian_colado(self, db_vieja):
        db_vieja([
            ("Nutricionista", "Aramark", "d1", "u1", NOT_APPLIED, "2026-01-01 10:00:00"),
            ("Nutricionista (H/F)", "Aramark", "d2", "u2", NOT_APPLIED, "2026-01-02 10:00:00"),
            ("NUTRICIONISTA", "aramark", "d3", "u3", NOT_APPLIED, "2026-01-03 10:00:00"),
        ])
        create_table()
        assert len(select_jobs()) == 1

    def test_al_fusionar_gana_el_que_ya_tenia_decision(self, db_vieja):
        """No se puede perder un 'Applied': es trabajo que ya hiciste."""
        db_vieja([
            ("Nutricionista", "Aramark", "d1", "u1", NOT_APPLIED, "2026-01-01 10:00:00"),
            ("Nutricionista (H/F)", "Aramark", "d2", "u2", APPLIED, "2026-01-02 10:00:00"),
        ])
        create_table()
        filas = select_jobs()
        assert len(filas) == 1
        assert filas[0][2] == APPLIED

    def test_conserva_los_discarded(self, db_vieja):
        db_vieja([
            ("Chef", "Sodexo", "d1", "u1", DISCARDED, "2026-01-01 10:00:00"),
            ("chef", "sodexo", "d2", "u2", NOT_APPLIED, "2026-01-02 10:00:00"),
        ])
        create_table()
        assert select_jobs()[0][2] == DISCARDED

    def test_deja_registro_en_el_log(self, db_vieja, workdir):
        db_vieja([("Nutricionista", "Aramark", "d", "u", NOT_APPLIED, "2026-01-01 10:00:00")])
        create_table()
        assert "clave normalizada" in (workdir / "log.txt").read_text(encoding="utf-8")

    def test_migrar_dos_veces_no_rompe(self, db_vieja):
        db_vieja([("Nutricionista", "Aramark", "d", "u", APPLIED, "2026-01-01 10:00:00")])
        assert create_table()
        assert create_table()
        assert len(select_jobs()) == 1
        assert select_jobs()[0][2] == APPLIED

    def test_no_queda_la_tabla_temporal(self, db_vieja, workdir):
        db_vieja([("Nutricionista", "Aramark", "d", "u", APPLIED, "2026-01-01 10:00:00")])
        create_table()
        tablas = [r[0] for r in sqlite3.connect(workdir / "jobs.db")
                  .execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "jobs_v1" not in tablas

    def test_base_vacia_tambien_migra(self, db_vieja):
        db_vieja([])
        assert create_table()
        assert select_jobs() == []
