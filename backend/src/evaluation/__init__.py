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
from .execution import (
    SemanticEvaluationRunner,
    SemanticExecutionError,
    run_semantic_evaluation,
)
from .providers.claude import (
    ClaudeOutputError,
    ClaudeProviderError,
    ClaudeSemanticEvaluator,
)
from .semantic import (
    PROHIBITED_VERDICTS,
    REASON_CODES,
    ExpectedElement,
    SemanticError,
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticEvaluator,
    SemanticRequestError,
    SemanticResultValidationError,
    SemanticVerdict,
    build_semantic_request,
    validate_semantic_result,
)

__all__ = [
    "ClaudeOutputError",
    "ClaudeProviderError",
    "ClaudeSemanticEvaluator",
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
    "PROHIBITED_VERDICTS",
    "REASON_CODES",
    "ExpectedElement",
    "SemanticError",
    "SemanticEvaluationRequest",
    "SemanticEvaluationResult",
    "SemanticEvaluationRunner",
    "SemanticEvaluator",
    "SemanticExecutionError",
    "SemanticRequestError",
    "SemanticResultValidationError",
    "SemanticVerdict",
    "build_semantic_request",
    "run_semantic_evaluation",
    "validate_semantic_result",
]
