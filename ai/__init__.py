"""Evaluacion de ofertas con AI."""

from ai.relevance import (
    NOT_EVALUATED,
    NOT_RELEVANT,
    RELEVANT,
    AlwaysRelevant,
    OpenAIRelevanceClassifier,
    RelevanceClassifier,
    Verdict,
    as_verdict,
    create_classifier,
    is_relevant,
)

__all__ = [
    "NOT_EVALUATED",
    "NOT_RELEVANT",
    "RELEVANT",
    "AlwaysRelevant",
    "OpenAIRelevanceClassifier",
    "RelevanceClassifier",
    "Verdict",
    "as_verdict",
    "create_classifier",
    "is_relevant",
]
