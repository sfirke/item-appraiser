"""Score an appraiser against the hand-valued test set.

    python -m item_appraiser.evaluate                      # category-median baseline
    python -m item_appraiser.evaluate --data path/to.csv --worst 10

Errors are measured as ratios (a $5 miss on a $10 item counts the same as a
$150 miss on a $300 one). Because the end goal is aggregate impact, the report
also shows total bias: the sum of predicted values over the sum of hand values.
"""

import argparse
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from item_appraiser import dataset, policy
from item_appraiser.baseline import CategoryMedianAppraiser
from item_appraiser.dataset import LabeledItem
from item_appraiser.models import Appraisal, Appraiser, Confidence

# Floor for log-ratio errors, so a $0 estimate scores as a large miss rather than infinity.
MIN_PRICE_USD = 0.01


@dataclass(frozen=True)
class Prediction:
    item: LabeledItem
    appraisal: Appraisal

    @property
    def log_ratio(self) -> float:
        """ln(predicted buy value / hand buy value); positive means overestimated."""
        predicted = max(policy.appraisal_buy_value(self.appraisal), MIN_PRICE_USD)
        actual = max(policy.appraisal_buy_value(self.item.label), MIN_PRICE_USD)
        return math.log(predicted / actual)


@dataclass(frozen=True)
class ErrorStats:
    """Ratio-scale error of one quantity across a set of predictions."""

    n: int
    median_ratio_error: float  # e.g. 1.4 means the typical estimate is off by a factor of 1.4
    within_25_pct: float
    within_2x: float
    total_ratio: float  # sum(predicted) / sum(actual); 1.0 is unbiased in aggregate

    @classmethod
    def compute(cls, pairs: Sequence[tuple[float, float]]) -> "ErrorStats":
        """`pairs` are (predicted, actual) values."""
        ratios = [max(p, MIN_PRICE_USD) / max(a, MIN_PRICE_USD) for p, a in pairs]
        abs_logs = [abs(math.log(r)) for r in ratios]
        return cls(
            n=len(pairs),
            median_ratio_error=math.exp(median(abs_logs)),
            within_25_pct=sum(0.8 <= r <= 1.25 for r in ratios) / len(ratios),
            within_2x=sum(0.5 <= r <= 2 for r in ratios) / len(ratios),
            total_ratio=sum(p for p, _ in pairs) / sum(a for _, a in pairs),
        )


@dataclass(frozen=True)
class Report:
    new_price: ErrorStats
    buy_value: ErrorStats
    loan_value: ErrorStats
    condition_accuracy: float
    buy_value_by_confidence: dict[Confidence, ErrorStats]
    worst: list[Prediction]


def predict(appraiser: Appraiser, items: Sequence[LabeledItem]) -> list[Prediction]:
    return [Prediction(item, appraiser.appraise(item.listing)) for item in items]


def predict_leave_one_out(
    build: Callable[[list[LabeledItem]], Appraiser], items: Sequence[LabeledItem]
) -> list[Prediction]:
    """Predict each item with an appraiser built from all the other items."""
    predictions = []
    for i, item in enumerate(items):
        appraiser = build([*items[:i], *items[i + 1 :]])
        predictions.append(Prediction(item, appraiser.appraise(item.listing)))
    return predictions


def score(predictions: Sequence[Prediction], worst: int = 5) -> Report:
    if not predictions:
        raise ValueError("no predictions to score")

    def stats(preds: Sequence[Prediction], value: Callable[[Appraisal], float]) -> ErrorStats:
        return ErrorStats.compute([(value(p.appraisal), value(p.item.label)) for p in preds])

    by_confidence = {}
    for confidence in Confidence:
        tier = [p for p in predictions if p.item.label.confidence == confidence]
        if tier:
            by_confidence[confidence] = stats(tier, policy.appraisal_buy_value)

    return Report(
        new_price=stats(predictions, lambda a: a.new_price_usd),
        buy_value=stats(predictions, policy.appraisal_buy_value),
        loan_value=stats(predictions, policy.appraisal_loan_value),
        condition_accuracy=sum(p.appraisal.condition == p.item.label.condition for p in predictions)
        / len(predictions),
        buy_value_by_confidence=by_confidence,
        worst=sorted(predictions, key=lambda p: abs(p.log_ratio), reverse=True)[:worst],
    )


def format_report(report: Report) -> str:
    lines = [
        f"{'':<22}{'n':>4}{'typical error':>15}{'within 25%':>12}{'within 2x':>11}{'total bias':>12}",
    ]

    def row(label: str, s: ErrorStats) -> str:
        return (
            f"{label:<22}{s.n:>4}{s.median_ratio_error:>14.2f}x{s.within_25_pct:>12.0%}"
            f"{s.within_2x:>11.0%}{s.total_ratio:>11.2f}x"
        )

    lines.append(row("new price", report.new_price))
    lines.append(row("buy value", report.buy_value))
    lines.append(row("loan value", report.loan_value))
    for confidence, s in report.buy_value_by_confidence.items():
        lines.append(row(f"  buy, {confidence} conf.", s))
    lines.append(f"\ncondition accuracy: {report.condition_accuracy:.0%}")

    if report.worst:
        lines.append("\nlargest disagreements (buy value, predicted vs hand):")
        for p in report.worst:
            predicted = policy.appraisal_buy_value(p.appraisal)
            actual = policy.appraisal_buy_value(p.item.label)
            lines.append(
                f"  {math.exp(abs(p.log_ratio)):>5.1f}x  ${predicted:>8.2f} vs ${actual:>8.2f}  "
                f"{p.item.listing.name}"
            )
    return "\n".join(lines)


# Each entry maps the full labeled set to predictions. Appraisers that learn from
# labels must be scored leave-one-out so they never see the item they predict.
APPRAISERS: dict[str, Callable[[Sequence[LabeledItem]], list[Prediction]]] = {
    "category-median": lambda items: predict_leave_one_out(CategoryMedianAppraiser, items),
}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=dataset.DEFAULT_PATH)
    parser.add_argument("--appraiser", choices=sorted(APPRAISERS), default="category-median")
    parser.add_argument("--worst", type=int, default=5, help="list the N largest disagreements")
    args = parser.parse_args(argv)

    items = dataset.load(args.data)
    print(f"{args.appraiser} on {len(items)} hand-valued items from {args.data}\n")
    print(format_report(score(APPRAISERS[args.appraiser](items), worst=args.worst)))


if __name__ == "__main__":
    main()
