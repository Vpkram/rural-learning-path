"""Bayesian Knowledge Tracing helpers for per-topic learner mastery."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class BKTParameters:
    """BKT probabilities: learning, lucky guess, and careless slip."""

    learn: float = 0.15
    guess: float = 0.20
    slip: float = 0.10

    def __post_init__(self) -> None:
        for name, value in (
            ("learn", self.learn),
            ("guess", self.guess),
            ("slip", self.slip),
        ):
            if not math.isfinite(value) or not 0 <= value < 1:
                raise ValueError(f"{name} must be a finite probability in [0, 1).")
        if self.guess == 0 or self.slip == 0:
            raise ValueError("guess and slip must be greater than zero.")


def update_mastery(
    prior_mastery: float,
    is_correct: bool,
    parameters: BKTParameters = BKTParameters(),
) -> float:
    """Update mastery after one answer, accounting for guesses, slips, and learning.

    First estimate how likely the learner knew the topic before answering.
    Then allow a small chance that answering the question helped them learn it.
    """
    if not math.isfinite(prior_mastery) or not 0 <= prior_mastery <= 1:
        raise ValueError("prior_mastery must be a finite value in [0, 1].")
    if not isinstance(is_correct, bool):
        raise TypeError("is_correct must be a bool.")

    if is_correct:
        observed_if_mastered = 1.0 - parameters.slip
        observed_if_unmastered = parameters.guess
    else:
        observed_if_mastered = parameters.slip
        observed_if_unmastered = 1.0 - parameters.guess

    mastered_likelihood = prior_mastery * observed_if_mastered
    unmastered_likelihood = (1.0 - prior_mastery) * observed_if_unmastered
    evidence = mastered_likelihood + unmastered_likelihood
    posterior = mastered_likelihood / evidence

    updated = posterior + (1.0 - posterior) * parameters.learn
    return min(1.0, max(0.0, updated))


def mastery_status(score: float) -> str:
    """Convert the 0-1 BKT estimate into a simple learner-facing label."""
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("score must be a finite value in [0, 1].")
    if score < 0.40:
        return "Weak"
    if score < 0.80:
        return "Developing"
    return "Strong"
