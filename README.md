# Job Hunter #
Obtiene una lista de trabajos desde una API, los evalúa con AI y guarda los relevantes en una base de datos SQLite local.

## Funcionamiento ##
1. Se consulta la API de trabajos configurada en `config.json`.
2. Cada trabajo que **no** esté ya en la base de datos se evalúa con AI para saber si es `relevante` o `no-relevante`.
3. Los `relevantes` se guardan en `jobs.db`, donde puedes marcar cuáles ya aplicaste.

La clave de los registros es el cargo y la empresa: si encuentra el mismo trabajo en una búsqueda futura no lo duplica.

Utilizamos OpenAI, por lo tanto debes tener la `OPENAI_API_KEY` definida en el entorno.

## Estructura del proyecto ##

```
main.py            Punto de entrada
config.py          Carga de config.json (con defaults y retrocompatibilidad)
models.py          JobPosting: el modelo canónico de la app

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

### Manejo de errores ###

* **Falla la API completa** (credencial, timeout, 5xx) → `ProviderError`. El cliente HTTP reintenta con backoff exponencial en 429/5xx/timeouts; si igual falla, la app muestra el mensaje y sigue viva.
* **Un trabajo viene mal o le falta un campo** → se registra en `log.txt` y se continúa con el siguiente. Un ítem malo nunca corta la búsqueda. Sin `title` o sin `organization` el trabajo se salta (son la clave primaria); cualquier otro campo ausente simplemente queda vacío.
* **Falla la AI en un trabajo** → se asume `relevante` (mejor revisar uno de más que perder uno bueno).
* **Falta `prompt.txt` o `langchain`** → la app funciona igual, guardando todos los trabajos sin filtrar.

## Configuración ##

Copia `config.json.example` a `config.json` y completa tu `rapidApiKey`.

```json
{
  "provider": "fantastic_linkedin",
  "rapidApiKey": "TU API KEY",
  "providers": {
    "fantastic_linkedin": {
      "endpoint": "active-jb-7d",
      "limit": 25,
      "titleFilter": "Contador Auditor",
      "locationFilter": "Chile",
      "descriptionType": "text"
    }
  }
}
```

API: [LinkedIn Job Search API (Fantastic Jobs)](https://rapidapi.com/fantastic-jobs-fantastic-jobs-default/api/linkedin-job-search-api)

| Opción | Descripción |
| --- | --- |
| `endpoint` | Ventana de tiempo: `active-jb-1h`, `active-jb-24h` o `active-jb-7d` |
| `limit` / `offset` | Cuántos trabajos traer (1-100) y desde dónde, para paginar |
| `titleFilter` | Filtro por cargo. Acepta `"Contador" OR "Auditor"` y `-Junior` para excluir |
| `advancedTitleFilter` | Filtro avanzado (sintaxis tsquery). Si se usa, reemplaza a `titleFilter` |
| `locationFilter` | Ubicación, ej: `"Chile" OR "Argentina"` |
| `descriptionFilter` | Filtra por texto dentro de la descripción |
| `organizationFilter` | Filtra por nombre de empresa |
| `descriptionType` | `text` o `html`. **Déjalo en `text`**: sin esto la API no devuelve la descripción y la AI no tendría qué evaluar |
| `remote` | `true` solo remotos, `false` solo presenciales, `null` sin filtrar |
| `includeAgencies` | `false` para excluir consultoras de reclutamiento |
| `includeAi` | `true` agrega los campos enriquecidos con AI (consume más cuota) |
| `seniorityFilter` | Ej: `Entry level`, `Mid-Senior level`, `Director` |
| `aiWorkArrangementFilter` | `On-site`, `Hybrid`, `Remote OK`, `Remote Solely` (requiere `includeAi`) |
| `dateFilter` | Solo trabajos desde una fecha, ej: `2026-07-01` |

Dejar una opción vacía (`""` o `null`) equivale a no filtrar por ella.

Las opciones compartidas `requestTimeout` (segundos) y `maxRetries` van en la raíz del archivo.

### Volver a la API anterior ###

Cambia `"provider": "linkedin_data_scraper"`. Su configuración antigua sigue funcionando tal cual.

## Configurar la AI para que determine si es relevante o no ##
La AI identifica si la oferta es relevante para ti basado en tus calificaciones y experiencia.

Esto se hace por medio del archivo `prompt.txt` (debes crearlo), que puede tener algo como:

```
Soy un contador en busca de trabajo, debes evaluar si el trabajo se ajusta a mis habilidades y requerimientos.

Mis habilidades son: contabilidad general, auditoría, análisis financiero, preparación de impuestos, contabilidad de costos, contabilidad de gestión, manejo de software contable (como QuickBooks y SAP), conciliaciones bancarias, gestión de presupuestos, informes financieros, cumplimiento normativo y asesoría fiscal.
```

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
