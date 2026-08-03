"""Identidad de un trabajo: como se decide si dos ofertas son la misma.

Por que vive aca y no dentro de cada proveedor
----------------------------------------------
La deduplicacion solo funciona si TODOS los origenes calculan la clave igual.
Si cada adapter normalizara a su manera, el mismo trabajo visto por dos APIs
(o por la misma API antes y despues de un cambio de formato) generaria dos
claves distintas y se guardaria dos veces. Justamente lo que queremos evitar.

El reparto de responsabilidades es:

    providers/   traducen el JSON de su API al modelo comun (adapter)
    identity.py  decide que significa "es el mismo trabajo" (politica de la app)
    db/          persiste usando esa clave

Si algun dia un proveedor tiene una mejor senal de identidad, el punto de
extension correcto es que llene `JobPosting.external_id` (un id estable de esa
API), no que invente su propia normalizacion.

Criterio de normalizacion: conservador
--------------------------------------
Solo se elimina ruido de *formato*, nunca contenido con significado. Por eso:

  - "C++" y "C#" NO se tocan: son lenguajes distintos, no puntuacion decorativa.
  - Los puntos y apostrofes se borran sin dejar espacio, para que "S.A." y "SA"
    (la misma empresa) den la misma clave.
  - Los sufijos de genero ("(H/F)", "(m/w/d)") se quitan porque son una
    convencion de LinkedIn por pais, no parte del cargo.

Ante la duda, se prefiere NO normalizar: un duplicado de mas es un problema
menor que dos ofertas distintas fusionadas en una.
"""

import re
import unicodedata

# Sufijos de genero que LinkedIn agrega al cargo segun el pais. Solo se quitan
# estas combinaciones concretas; cualquier otro parentesis se respeta, porque
# suele traer informacion real ("(Remote)", "(Senior)", "(Turno Noche)").
GENDER_SUFFIX = re.compile(
    r"\(\s*(?:h/f|f/h|m/f|f/m|h/m|m/w|w/m|m/w/d|w/m/d|d/m/w|m/f/d|f/m/d|m/v|v/m)\s*\)",
    re.IGNORECASE,
)

# Se borran sin dejar separacion: "S.A." -> "sa", "L'Oreal" -> "loreal".
PUNTUACION_MUDA = re.compile(r"[.'’`]")

# Caracteres que SI significan algo en un cargo y por eso sobreviven.
SIGNIFICATIVOS = "+#"

_SEPARADORES = re.compile(rf"[^0-9a-z{re.escape(SIGNIFICATIVOS)}]+")


def normalize_key_part(text: str) -> str:
    """Normaliza un trozo de la clave, quitando solo ruido de formato.

    Estas cuatro variantes son el MISMO trabajo:

        "Nutricionista"  "Nutricionista (H/F)"  "nutricionista"  "Nutricionista "

    Estos tres NO lo son, y siguen dando claves distintas:

        "C++ Developer"  "C# Developer"  "C Developer"
    """
    if not text:
        return ""

    text = GENDER_SUFFIX.sub(" ", text)

    # NFD (descomposicion canonica) separa la tilde de la letra para poder
    # descartarla: "nutrición" -> "nutricion".
    #
    # Es NFD y no NFKD a proposito: la descomposicion de compatibilidad
    # convierte simbolos en letras ("Bulk™" -> "bulktm", "½" -> "1 2"), o sea
    # inventa contenido. Con NFD el simbolo se mantiene y despues lo descarta
    # el regex de separadores, que es lo que queremos.
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))

    text = PUNTUACION_MUDA.sub("", text.lower())
    text = _SEPARADORES.sub(" ", text)
    return " ".join(text.split())


def build_job_key(title: str, company: str) -> str:
    """Clave logica de un trabajo: cargo + empresa, normalizados.

    Es la misma identidad que recomienda la documentacion de la API
    ("title + organization"); lo que cambia respecto de la version anterior es
    que ahora se compara normalizada en vez de caracter por caracter.
    """
    return f"{normalize_key_part(title)}|{normalize_key_part(company)}"
