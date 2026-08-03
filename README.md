# Job Hunter #
Obtiene una lista de trabajos desde una API, los evalúa con AI y guarda los relevantes en una base de datos SQLite local.

## Funcionamiento ##
1. Se consulta la API de trabajos configurada en `config.json`.
2. Cada trabajo que **no** esté ya en la base de datos se evalúa con AI, que le pone un puntaje de 0 a 100 y una línea explicando por qué.
3. Los que llegan al corte (`ai.minScore`, por defecto 60) se guardan en `jobs.db`, donde puedes marcar cuáles ya aplicaste. Los descartados también se guardan, pero fuera de la grilla: así no se le vuelve a pagar al LLM por el mismo trabajo en cada búsqueda.

La clave de los registros es el cargo y la empresa: si encuentra el mismo trabajo en una búsqueda futura no lo duplica. Ver [Identidad de un trabajo](#identidad-de-un-trabajo).

Utilizamos OpenAI, por lo tanto debes tener la `OPENAI_API_KEY` definida en el entorno.

## Estructura del proyecto ##

```
main.py            Punto de entrada
config.py          Carga de config.json (con defaults y retrocompatibilidad)
models.py          JobPosting: el modelo canónico de la app
identity.py        Cuándo dos ofertas son el mismo trabajo (clave normalizada)

utils/             Utilidades transversales
  safe.py                    Accesores tolerantes a fallas para JSON de APIs
  log.py                     Log a log.txt
  resources.py               Rutas a assets (funciona en fuente y en el .exe)

providers/         Capa de acceso a APIs (ports & adapters)
  base.py                    JobSource (Protocol), FetchResult, map_items
  http.py                    Cliente HTTP con timeouts y reintentos
  fantastic_linkedin.py      LinkedIn Job Search API (activa)
  linkedin_data_scraper.py   API anterior (se mantiene para volver atrás)
  registry.py                Registro nombre -> constructor

ai/                Clasificación de relevancia (RelevanceClassifier)
db/                SQLite (mismo esquema de siempre)
services/          job_hunt: orquesta API -> AI -> DB
ui/                Interfaz Tkinter
```

### Cómo está desacoplada la API ###

El resto de la aplicación nunca ve el JSON de un proveedor: trabaja siempre con `JobPosting`.
El contrato es un `Protocol`, no una clase base, así que un proveedor no hereda de nada:

```python
class JobSource(Protocol):
    name: str
    def fetch(self) -> FetchResult: ...
```

Cada proveedor separa dos cosas:

* **`to_posting(raw) -> JobPosting | None`** — función pura, sin red. Se puede probar con un JSON guardado en disco.
* **La clase `...Source`** — arma los parámetros y llama al cliente HTTP compartido.

**Para agregar una API nueva:**

1. Crear `providers/mi_api.py` con `to_posting()`, una clase con `name` y `fetch()`, y una función `build(settings)`.
2. Agregar una línea en `BUILDERS` dentro de `providers/registry.py`.
3. Poner `"provider": "mi_api"` y su bloque de opciones en `config.json`.

No cambia nada más del proyecto.

### Identidad de un trabajo ###

Dos ofertas son la misma si coinciden **cargo + empresa normalizados** — la identidad que recomienda
la propia documentación de la API. La normalización vive en [identity.py](identity.py) y se aplica
igual para todos los proveedores: si cada adapter normalizara a su manera, el mismo trabajo visto por
dos APIs generaría dos filas.

Se quita solo ruido de formato:

| Estas son el **mismo** trabajo | Estos son trabajos **distintos** |
| --- | --- |
| `Nutricionista` | `C++ Developer` |
| `Nutricionista (H/F)` | `C# Developer` |
| `nutricionista` | `C Developer` |
| `NUTRICIONISTA ` | `Chef` vs `Chef (Remote)` |
| `Aramark S.A.` = `Aramark SA` | `Contador` vs `Contadora` |

El criterio es conservador: ante la duda **no** se normaliza, porque un duplicado de más molesta
menos que dos ofertas distintas fusionadas en una. Por eso solo se eliminan los sufijos de género
(`(H/F)`, `(m/w/d)`) y no cualquier paréntesis, y se conservan `+` y `#`.

Lo que **sí** depende del proveedor es de dónde sale el cargo y la empresa (`organization` en una API,
`companyName` en otra); eso vive en el `to_posting()` de cada adapter. Si algún día un proveedor tiene
una señal de identidad mejor, el punto de extensión es `JobPosting.external_id`, no una normalización
propia.

La tabla usa una columna `job_key` como clave primaria. Una `jobs.db` del esquema anterior **se migra
sola** al abrir la app: se recalculan las claves y, si dos filas antiguas resultan ser el mismo
trabajo, gana la que ya tenía una decisión tomada (`Applied` / `Discarded`) para no perder trabajo ya
hecho. Queda anotado en `log.txt`.

### Manejo de errores ###

* **Falla la API completa** (credencial, timeout, 5xx) → `ProviderError`. El cliente HTTP reintenta con backoff exponencial en 429/5xx/timeouts; si igual falla, la app muestra el mensaje y sigue viva.
* **Un trabajo viene mal o le falta un campo** → se registra en `log.txt` y se continúa con el siguiente. Un ítem malo nunca corta la búsqueda. Sin `title` o sin `organization` el trabajo se salta (son la clave primaria); cualquier otro campo ausente simplemente queda vacío.
* **Falla la AI en un trabajo** → se asume `relevante` con puntaje `-1` ("no evaluado"): mejor revisar uno de más que perder uno bueno. Como no queda descartado, se vuelve a evaluar en la próxima búsqueda.
* **Falta `prompt.txt` o `langchain`** → la app funciona igual, guardando todos los trabajos sin filtrar.

## Configuración ##

Copia `config.json.example` a `config.json` y completa tu `rapidApiKey`.

```json
{
  "provider": "fantastic_linkedin",
  "rapidApiKey": "TU API KEY",
  "providers": {
    "fantastic_linkedin": {
      "search": {
        "time_frame": "24h",
        "limit": 25,
        "description_format": "text",
        "title": "Contador Auditor",
        "location": "Chile"
      }
    }
  }
}
```

API: [LinkedIn Job Search API (Fantastic Jobs)](https://rapidapi.com/fantastic-jobs-fantastic-jobs-default/api/linkedin-job-search-api) — endpoint `GET /active-jb`.

**Las claves dentro de `search` son los nombres reales de los parámetros de la API**, así que la
página de documentación sirve directamente como referencia y no hay una tabla de traducción que se
desactualice. Los más usados:

| Parámetro | Descripción |
| --- | --- |
| `time_frame` | Ventana de tiempo. Solo `1h`, `24h`, `7d` o `6m` (no existe `3d`) |
| `limit` / `offset` | Cuántos trabajos traer (1-100) y desde dónde, para paginar |
| `description_format` | `text` o `html`. **Déjalo en `text`**: sin esto la API no devuelve `description_text` y la AI no tendría qué evaluar |
| `title` | Filtro por cargo. `software engineer` (ambas palabras), `software OR engineer`, `-junior` para excluir |
| `title_advanced` | Booleano: `&` AND, `\|` OR, `!` NOT, `<->` seguido-de, `:*` prefijo. Si se usa, ignora `title` |
| `location` | Nombres completos, sin abreviaturas: `Chile`, `"United States" OR "United Kingdom"` |
| `description` | Busca en título + descripción combinados |
| `organization` | Nombre de empresa. Exacto y sensible a mayúsculas |
| `seniority` | `Internship`, `Entry level`, `Associate`, `Mid-Senior level`, `Director`, `Executive`, `Not Applicable` |
| `organization_agency` | `exclude` para omitir consultoras de reclutamiento, `only` para solo ellas |
| `ai_work_arrangement` | `On-site`, `Hybrid`, `Remote OK`, `Remote Solely` (lista separada por coma) |
| `ai_experience_level` | `0-2`, `2-5`, `5-10`, `10+` |
| `ai_employment_type` | `FULL_TIME`, `PART_TIME`, `CONTRACTOR`, `TEMPORARY`, `INTERN`... |
| `has_salary` | `true` para solo ofertas con renta publicada |
| `date_posted_gte` | Solo publicados desde una fecha ISO, ej: `2026-07-01T00:00:00` |

La lista completa está en [providers/fantastic_linkedin.py](providers/fantastic_linkedin.py) (`SUPPORTED_PARAMS`).
Un parámetro mal escrito **no rompe la búsqueda**: se descarta y queda anotado en `log.txt`.

### Créditos del plan ###

La API cobra **dos contadores distintos**, y conviene entenderlos antes de tocar `limit`:

* **requests** — 1 por cada llamada. Cada click en `Hunt!` gasta 1.
* **jobs** — 1 por cada trabajo devuelto.

En el plan BASIC son 25 requests y 250 jobs al mes, o sea **10 trabajos por llamada** para que ambos
se acaben a la vez. Subir `limit` no gasta requests extra: trae más trabajos en la misma llamada.

La app lee los créditos restantes de las cabeceras de cada respuesta y los muestra en la barra de
estado y en `log.txt`:

```
4 nuevos | 0 ya guardados | 2 descartados por AI | 6 revisados  [cuota restante: jobs 172/250, requests 8/25, renueva en 30d]
```

Si se agota la cuota, el mensaje lo dice explícitamente y **no reintenta** (reintentar no serviría):

```
Error: Se agoto la cuota del plan. cuota restante: jobs 172/250, requests 0/25, renueva en 30d.
```

Las opciones compartidas `requestTimeout` (segundos) y `maxRetries` van en la raíz del archivo.

> Ojo: el campo `seniority` que devuelve la API viene en el idioma del aviso (por ejemplo `Cadre` en
> Francia), no siempre en inglés. Para filtrar de forma independiente del mercado conviene
> `ai_experience_level`.

### Volver a la API anterior ###

Cambia `"provider": "linkedin_data_scraper"`. Su configuración antigua sigue funcionando tal cual.

## Configurar la AI para que determine si es relevante o no ##
La AI identifica si la oferta es relevante para ti basado en tus calificaciones y experiencia.

Esto se hace por medio del archivo `prompt.txt` (debes crearlo), que puede tener algo como:

```
Soy un contador en busca de trabajo, debes evaluar si el trabajo se ajusta a mis habilidades y requerimientos.

Mis habilidades son: contabilidad general, auditoría, análisis financiero, preparación de impuestos, contabilidad de costos, contabilidad de gestión, manejo de software contable (como QuickBooks y SAP), conciliaciones bancarias, gestión de presupuestos, informes financieros, cumplimiento normativo y asesoría fiscal.
```

### El corte lo pones tú ###

El modelo no decide si un trabajo entra: entrega un puntaje de 0 a 100 y un motivo. Quién pasa se define en `config.json`:

```json
"ai": { "minScore": 60 }
```

Súbelo si te está dejando pasar cosas que no te sirven, bájalo si crees que está filtrando de más. El puntaje se ve en la columna `Score` de la grilla y el motivo aparece arriba de la descripción, así puedes ajustar el corte (o el `prompt.txt`) mirando resultados y no a ciegas.

Cambiar el `minScore` **no** re-evalúa lo ya guardado: un trabajo descartado con el corte anterior queda descartado. Si quieres volver a empezar con el criterio nuevo, usa *Vaciar DB*.

## Entorno virtual ##

Crear entorno

`python -m venv .venv`

Activar entorno

`.venv\Scripts\Activate`

## Instalar dependencias ##
`pip install -r requirements.txt`

La búsqueda de trabajos y la base de datos usan solo la librería estándar; las dependencias son para la parte de AI.

## Ejecutar ##
`python main.py`

## Tests ##

Se usa **pytest** (el equivalente a vitest en el mundo Python).

```
pip install pytest

pytest                    # por defecto: SIN red, no gasta ni un request de cuota
pytest --live             # opt-in explícito: además llama a la API real
pytest -m "not gui"       # omite los que abren una ventana Tk
pytest -k mapeo -v        # filtra por nombre, como `vitest -t`
pytest --lf               # solo los que fallaron la última vez
```

### La cuota está protegida por partida doble ###

El plan BASIC son **25 requests y 250 jobs al mes**, así que una suite que llame a la API sin querer
se lleva el mes por delante. Hay dos barreras, en [tests/conftest.py](tests/conftest.py):

1. **Los tests `live` no se ejecutan** salvo que pases `--live`. Ni se intentan: se saltan en la fase
   de colección.
2. **La red está bloqueada** en todo test que no esté marcado `live`. Si alguien escribe un test
   nuevo y se olvida de usar un doble, falla con un mensaje que explica qué hacer, en vez de gastar
   cuota en silencio.

[tests/test_proteccion_cuota.py](tests/test_proteccion_cuota.py) verifica que ambas barreras siguen
funcionando, para que esta protección no se rompa sin que nadie se dé cuenta.

| Archivo | Qué cubre |
| --- | --- |
| [tests/test_safe.py](tests/test_safe.py) | Los accesores tolerantes nunca lanzan, con cualquier basura de entrada |
| [tests/test_config.py](tests/test_config.py) | Defaults, config plano antiguo, `prompt.txt` en UTF-8/ANSI/BOM |
| [tests/test_providers.py](tests/test_providers.py) | Parámetros, mapeo de la respuesta real, aislamiento de items malos |
| [tests/test_db.py](tests/test_db.py) | Esquema SQLite, sin duplicados, errores que no propagan |
| [tests/test_job_key.py](tests/test_job_key.py) | Normalización de la clave y migración del esquema viejo |
| [tests/test_ai.py](tests/test_ai.py) | Que `prompt.txt` llegue al LLM y la normalización de la respuesta |
| [tests/test_job_hunt.py](tests/test_job_hunt.py) | Flujo completo API → AI → base de datos |
| [tests/test_resources.py](tests/test_resources.py) | Assets, icono, ventana Tk real (marcados `gui`) |
| [tests/test_quota.py](tests/test_quota.py) | Lectura de los créditos restantes que informa la API |
| [tests/test_proteccion_cuota.py](tests/test_proteccion_cuota.py) | Que la suite normal no pueda salir a internet |
| [tests/test_live_api.py](tests/test_live_api.py) | API real (marcados `live`, solo con `--live`) |

Detalles que vale la pena conocer:

* **No hace falta librería de mocking.** Como los puertos son `Protocol`, un doble de prueba es una
  clase normal con los mismos métodos — ver `FakeSource` y `FakeClassifier` en
  [tests/test_job_hunt.py](tests/test_job_hunt.py).
* **Cada test corre en su propia carpeta temporal** (fixture `workdir` en
  [tests/conftest.py](tests/conftest.py)), así que nunca tocan tu `jobs.db`, `log.txt` ni `config.json`.
* **[tests/fixtures/active_jb_sample.json](tests/fixtures/active_jb_sample.json)** es una respuesta
  real de la API guardada en disco: permite probar el mapeo sin red y sin gastar cuota.
* Los tests `live` sirven de alarma: si un día fallan **solo ellos**, la API cambió — no tu código.

## Compilar a ejecutable ##
```
pyinstaller -n "Job Hunter" --collect-all langchain --noconfirm --windowed ^
  --icon=assets/favicon.ico --add-data "assets/favicon.ico;assets" main.py
```

`--icon` pone el icono al archivo .exe (el que se ve en el explorador), pero **no** el de la ventana.
El `--add-data` incluye el `.ico` dentro del ejecutable para que la app también lo pueda aplicar a la
ventana y a la barra de tareas en tiempo de ejecución. En Linux/macOS el separador es `:` en vez de `;`.

El `config.json` y el `prompt.txt` **no** se empaquetan: van junto al ejecutable, para poder editarlos
sin recompilar.
