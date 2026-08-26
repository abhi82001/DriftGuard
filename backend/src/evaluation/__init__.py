"""DriftGuard deterministic evaluation engine package.

Public API for Checkpoint 002. The engine executes evaluation mechanics only;
the knowledge base supplies all compliance meaning.
"""

from .engine import (
    EVAL_DETERMINISTIC,
    EVAL_SEMANTIC,
    GAP_GRAMMAR_VERSION,
    OUTCOME_FIRED,
    OUTCOME_NOT_FIRED,
    OUTCOME_SEMANTIC_REQUIRED,
    EngineError,
    EvaluationEngine,
    InvalidAnswerError,
    KnowledgeBase,
    KnowledgeError,
    MalformedConditionError,
    QuestionEvaluation,
    SignalResult,
    UnsupportedGrammarVersionError,
    UnsupportedOperatorError,
    evaluate_condition_expr,
    resolve_knowledge_root,
)

__all__ = [
    "EVAL_DETERMINISTIC",
    "EVAL_SEMANTIC",
    "GAP_GRAMMAR_VERSION",
    "OUTCOME_FIRED",
    "OUTCOME_NOT_FIRED",
    "OUTCOME_SEMANTIC_REQUIRED",
    "EngineError",
    "EvaluationEngine",
    "InvalidAnswerError",
    "KnowledgeBase",
    "KnowledgeError",
    "MalformedConditionError",
    "QuestionEvaluation",
    "SignalResult",
    "UnsupportedGrammarVersionError",
    "UnsupportedOperatorError",
    "evaluate_condition_expr",
    "resolve_knowledge_root",
]
