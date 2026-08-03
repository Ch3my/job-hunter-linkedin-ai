"""Clasificador de relevancia de una oferta de trabajo.

Mismo criterio de diseno que los proveedores: `RelevanceClassifier` es un
Protocol, no una clase base. Cambiar de LLM (o poner uno falso en un test) es
escribir otro objeto con el metodo `classify`.

Politica ante errores: si el LLM falla, se devuelve "relevante". Es preferible
revisar un trabajo de mas que perder uno bueno por un error de red.
"""

from typing import Optional, Protocol, runtime_checkable

from config import read_prompt_file
from models import JobPosting
from utils import append_to_log, log_exception

RELEVANT = "relevante"
NOT_RELEVANT = "no-relevante"

SYSTEM_PROMPT = (
    "Eres un asistente que se encarga de evaluar si un trabajo se adecua a los "
    'requerimientos, tu respuesta (en minuscula) es la clasificacion del trabajo '
    '(una de dos opciones) "relevante" o "no-relevante". Si no sabes si es '
    'relevante o no, contesta con "relevante"'
)

DEFAULT_MODEL = "gpt-5-mini-2025-08-07"


@runtime_checkable
class RelevanceClassifier(Protocol):
    def classify(self, posting: JobPosting) -> str:
        ...


class AlwaysRelevant:
    """Fallback cuando no hay prompt.txt o no hay LLM disponible.

    Deja pasar todo, de modo que la app sigue sirviendo como buscador aunque
    no este configurada la parte de AI. `reason` explica por que no se esta
    filtrando; `job_hunt` la muestra en la barra de estado para que no pase
    inadvertido que la AI quedo fuera.
    """

    reason = ""

    def __init__(self, reason: str = ""):
        self.reason = reason
        if reason:
            append_to_log(f"[ai] SIN FILTRO AI: {reason}")

    def classify(self, posting: JobPosting) -> str:
        return RELEVANT


class OpenAIRelevanceClassifier:
    """Clasificador con LangChain + OpenAI (requiere OPENAI_API_KEY)."""

    def __init__(self, user_profile: str, model: str = DEFAULT_MODEL, temperature: float = 1.0):
        # Import diferido: la app arranca aunque langchain no este instalado.
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        self.user_profile = user_profile
        prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("user", user_profile + "\n\n{job}")]
        )
        self.chain = prompt | ChatOpenAI(model=model, temperature=temperature) | StrOutputParser()

    def classify(self, posting: JobPosting) -> str:
        try:
            answer = self.chain.invoke({"job": posting.text_for_ai()})
        except Exception as error:
            log_exception(f"classify({posting.title})", error)
            return RELEVANT  # ante la duda, lo dejamos pasar

        answer = (answer or "").strip().lower()
        return NOT_RELEVANT if NOT_RELEVANT in answer else RELEVANT


def create_classifier(prompt_file: str = "prompt.txt") -> RelevanceClassifier:
    """Arma el clasificador segun lo que haya disponible en el entorno.

    Nunca lanza excepcion: si algo falta, devuelve `AlwaysRelevant` con el
    motivo, y la busqueda igual funciona.
    """
    profile = (read_prompt_file(prompt_file) or "").strip()
    if not profile:
        return AlwaysRelevant(
            f"No se encontro (o esta vacio) '{prompt_file}': se guardaran todos los trabajos sin filtrar."
        )

    try:
        classifier = OpenAIRelevanceClassifier(profile)
        append_to_log(f"[ai] perfil cargado desde '{prompt_file}' ({len(profile)} caracteres)")
        return classifier
    except ImportError as error:
        log_exception("create_classifier", error)
        return AlwaysRelevant("Falta langchain-openai, se guardaran todos los trabajos sin filtrar.")
    except Exception as error:
        log_exception("create_classifier", error)
        return AlwaysRelevant("No se pudo iniciar el LLM (revisa OPENAI_API_KEY), se guardaran todos los trabajos.")


def is_relevant(answer: Optional[str]) -> bool:
    return (answer or RELEVANT).strip().lower() != NOT_RELEVANT
