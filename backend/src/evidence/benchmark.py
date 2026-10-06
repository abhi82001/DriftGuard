#!/usr/bin/env python3
"""Ground-truth benchmark helpers for deterministic evidence extraction.

The benchmark deliberately separates *required targets* from other legitimate
facts.  Positive cases say which fact(s) must be recovered.  Negative cases say
that no material fact may be asserted.  This avoids pretending that a small
fixture set exhaustively annotates every possible attribute in a sentence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from claims import DemoClaimExtractor
from ingestion import Chunk, Document


@dataclass(frozen=True)
class BenchmarkMetrics:
    cases: int
    positive_cases: int
    negative_cases: int
    required_targets: int
    recovered_targets: int
    negative_predictions: int

    @property
    def target_recall(self) -> float:
        return self.recovered_targets / self.required_targets if self.required_targets else 1.0

    @property
    def negative_case_specificity(self) -> float:
        return ((self.negative_cases - self.negative_predictions) / self.negative_cases
                if self.negative_cases else 1.0)

    @property
    def false_inference_rate(self) -> float:
        return self.negative_predictions / self.negative_cases if self.negative_cases else 0.0

    def to_dict(self) -> dict:
        return {
            'cases': self.cases,
            'positive_cases': self.positive_cases,
            'negative_cases': self.negative_cases,
            'required_targets': self.required_targets,
            'recovered_targets': self.recovered_targets,
            'target_recall': round(self.target_recall, 4),
            'negative_case_specificity': round(self.negative_case_specificity, 4),
            'false_inference_rate': round(self.false_inference_rate, 4),
        }


def flatten_claims(text: str, filename: str) -> dict[str, object]:
    kind = 'policy' if 'policy' in filename.lower() else 'artifact'
    doc = Document(filename, kind, (Chunk(filename, 'benchmark line 1', text),))
    claims = DemoClaimExtractor().extract((doc,))
    out: dict[str, object] = {}
    for claim in claims:
        for key, value in claim.attributes.items():
            out[f'{claim.topic}.{key}'] = value
    return out


def evaluate_cases(cases: Iterable[dict]) -> tuple[BenchmarkMetrics, list[dict]]:
    cases = list(cases)
    positive = negative = required = recovered = negative_predictions = 0
    failures: list[dict] = []
    for case in cases:
        expected = case.get('expected', {})
        predicted = flatten_claims(case['text'], case.get('filename', 'evidence.txt'))
        if expected:
            positive += 1
            required += len(expected)
            errors = []
            for key, wanted in expected.items():
                if key not in predicted:
                    errors.append(f'missing {key}')
                elif wanted is not None and predicted[key] != wanted:
                    errors.append(f'{key}: expected {wanted!r}, got {predicted[key]!r}')
                else:
                    recovered += 1
            if errors:
                failures.append({'id': case['id'], 'errors': errors, 'predicted': predicted})
        else:
            negative += 1
            if predicted:
                negative_predictions += 1
                failures.append({
                    'id': case['id'],
                    'errors': ['negative case produced material fact(s)'],
                    'predicted': predicted,
                })
    return BenchmarkMetrics(len(cases), positive, negative, required, recovered,
                            negative_predictions), failures
