"""Input guardrails for economic scope and FRED answerability."""

from __future__ import annotations

from harness.guardrails.base import GuardrailResult


ECONOMIC_TERMS = {
    "cpi",
    "consumer price",
    "economic",
    "economy",
    "employment",
    "federal funds",
    "federal reserve",
    "fed",
    "gdp",
    "gross domestic product",
    "inflation",
    "interest rate",
    "interest rates",
    "labor",
    "prices",
    "productivity",
    "recession",
    "unemployment",
    "wage",
    "wages",
}

FORECASTING_TERMS = {
    "forecast",
    "forecasting",
    "future",
    "next month",
    "next quarter",
    "next year",
    "predict",
    "prediction",
    "projection",
    "will ",
}

NORMATIVE_TERMS = {
    "recommend",
    "recommendation",
    "should",
    "ought",
    "best policy",
}


class EconomicScopeGuardrail:
    """Allow economic measurement and explanatory questions."""

    def evaluate(self, question: str) -> GuardrailResult:
        text = _normalize(question)
        if any(term in text for term in ECONOMIC_TERMS):
            return GuardrailResult.pass_result("Question is in economic scope.")

        return GuardrailResult.fail_result(
            guardrail_name=self.__class__.__name__,
            stage="input",
            message="Question is outside economic scope.",
            recommended_action="escalate",
            severity="critical",
            context={"question": question},
        )


class FredAnswerableGuardrail:
    """Reject forecasting and normative policy questions for the FRED-only harness."""

    def evaluate(self, question: str) -> GuardrailResult:
        text = _normalize(question)

        if any(term in text for term in FORECASTING_TERMS):
            return self._fail(question, "Forecasting questions are not FRED-answerable.")

        if any(term in text for term in NORMATIVE_TERMS):
            return self._fail(
                question,
                "Normative policy recommendations are not FRED-answerable.",
            )

        if any(term in text for term in ECONOMIC_TERMS):
            return GuardrailResult.pass_result(
                "Question can be materially supported by FRED data."
            )

        return self._fail(question, "Question is not materially supported by FRED data.")

    def _fail(self, question: str, message: str) -> GuardrailResult:
        return GuardrailResult.fail_result(
            guardrail_name=self.__class__.__name__,
            stage="input",
            message=message,
            recommended_action="escalate",
            severity="critical",
            context={"question": question},
        )


class PromptInjectionGuardrail:
    """Stub guardrail reserved for prompt-injection detection."""

    def evaluate(self, question: str) -> GuardrailResult:
        return GuardrailResult.pass_result("Prompt injection stub passed.")


class DataSecurityGuardrail:
    """Stub guardrail reserved for data-security checks."""

    def evaluate(self, question: str) -> GuardrailResult:
        return GuardrailResult.pass_result("Data security stub passed.")


def _normalize(value: str) -> str:
    return " ".join(str(value).lower().split())
