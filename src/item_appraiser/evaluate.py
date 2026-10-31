"""Score an appraiser against the hand-valued test set.

    python -m item_appraiser.evaluate                      # category-median baseline
    python -m item_appraiser.evaluate --data path/to.csv --worst 10
    python -m item_appraiser.evaluate --appraiser claude --model haiku --limit 5

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

from dotenv import find_dotenv, load_dotenv

from item_appraiser import claude, dataset, policy
from item_appraiser.baseline import CategoryMedianAppraiser
from item_appraiser.claude import AppraisalError, ClaudeAppraiser
from item_appraiser.dataset import LabeledItem
from item_appraiser.models import Appraisal, Appraiser, Confidence, ResaleDemand

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
class QuantityStats:
    """Counted units against hand labels, over items where both exist."""

    n: int
    exact: float
    overcounted: int
    undercounted: int
    mismatches: list[Prediction]


@dataclass(frozen=True)
class Report:
    new_price: ErrorStats
    buy_value: ErrorStats
    loan_value: ErrorStats
    condition_accuracy: float
    buy_value_by_confidence: dict[Confidence, ErrorStats]
    buy_value_by_model_confidence: dict[Confidence, ErrorStats]
    quantity: QuantityStats | None
    weak_resale_mismatches: list[Prediction]
    worst: list[Prediction]


@dataclass(frozen=True)
class Failure:
    item: LabeledItem
    reason: str


@dataclass(frozen=True)
class Run:
    """The outcome of running an appraiser over the labeled set."""

    predictions: list[Prediction]
    failures: Sequence[Failure] = ()
    notes: str = ""


def predict(appraiser: Appraiser, items: Sequence[LabeledItem]) -> list[Prediction]:
    return [Prediction(item, appraiser.appraise(item.listing)) for item in items]


def predict_collecting_failures(
    appraiser: Appraiser, items: Sequence[LabeledItem]
) -> tuple[list[Prediction], list[Failure]]:
    """Predict what we can, so one bad listing doesn't lose the rest of a paid run."""
    predictions, failures = [], []
    for item in items:
        try:
            predictions.append(Prediction(item, appraiser.appraise(item.listing)))
        except AppraisalError as e:
            failures.append(Failure(item, str(e)))
    return predictions, failures


def predict_leave_one_out(
    build: Callable[[list[LabeledItem]], Appraiser], items: Sequence[LabeledItem]
) -> list[Prediction]:
    """Predict each item with an appraiser built from all the other items."""
    predictions = []
    for i, item in enumerate(items):
        appraiser = build([*items[:i], *items[i + 1 :]])
        predictions.append(Prediction(item, appraiser.appraise(item.listing)))
    return predictions


def score_quantity(predictions: Sequence[Prediction]) -> QuantityStats | None:
    labeled = [
        p
        for p in predictions
        if p.item.label.quantity is not None and p.appraisal.quantity is not None
    ]
    if not labeled:
        return None
    return QuantityStats(
        n=len(labeled),
        exact=sum(p.appraisal.quantity == p.item.label.quantity for p in labeled) / len(labeled),
        overcounted=sum(p.appraisal.quantity > p.item.label.quantity for p in labeled),
        undercounted=sum(p.appraisal.quantity < p.item.label.quantity for p in labeled),
        mismatches=[p for p in labeled if p.appraisal.quantity != p.item.label.quantity],
    )


def score(predictions: Sequence[Prediction], worst: int = 5) -> Report:
    if not predictions:
        raise ValueError("no predictions to score")

    def stats(preds: Sequence[Prediction], value: Callable[[Appraisal], float]) -> ErrorStats:
        return ErrorStats.compute([(value(p.appraisal), value(p.item.label)) for p in preds])

    def by_confidence(confidence_of: Callable[[Prediction], Confidence | None]):
        tiers = {}
        for confidence in Confidence:
            tier = [p for p in predictions if confidence_of(p) == confidence]
            if tier:
                tiers[confidence] = stats(tier, policy.appraisal_buy_value)
        return tiers

    return Report(
        new_price=stats(predictions, lambda a: a.new_price_usd),
        buy_value=stats(predictions, policy.appraisal_buy_value),
        loan_value=stats(predictions, policy.appraisal_loan_value),
        condition_accuracy=sum(p.appraisal.condition == p.item.label.condition for p in predictions)
        / len(predictions),
        buy_value_by_confidence=by_confidence(lambda p: p.item.label.confidence),
        buy_value_by_model_confidence=by_confidence(lambda p: p.appraisal.confidence),
        quantity=score_quantity(predictions),
        weak_resale_mismatches=[
            p for p in predictions if p.appraisal.resale_demand != p.item.label.resale_demand
        ],
        worst=sorted(predictions, key=lambda p: abs(p.log_ratio), reverse=True)[:worst],
    )


def describe_appraisal(appraisal: Appraisal) -> str:
    """One review line: how the new price was reached, and what the appraiser assumed."""
    if appraisal.quantity is not None and appraisal.unit_new_price_usd is not None:
        price = f"{appraisal.quantity} x ${appraisal.unit_new_price_usd:.2f}"
    elif appraisal.quantity is not None:
        price = f"{appraisal.quantity} for ${appraisal.new_price_usd:.2f}"
    else:
        price = f"${appraisal.new_price_usd:.2f}"
    text = f"{price} new, {appraisal.condition}"
    if appraisal.resale_demand == ResaleDemand.WEAK:
        text += ", weak resale"
    if appraisal.confidence:
        text += f", {appraisal.confidence} conf."
    if appraisal.assumptions:
        text += f": {appraisal.assumptions}"
    return text


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
    for confidence, s in report.buy_value_by_model_confidence.items():
        lines.append(row(f"  buy, model {confidence}", s))
    lines.append(f"\ncondition accuracy: {report.condition_accuracy:.0%}")

    if report.quantity:
        q = report.quantity
        lines.append(
            f"quantity accuracy: {q.exact:.0%} of {q.n} "
            f"({q.overcounted} overcounted, {q.undercounted} undercounted)"
        )
        for p in q.mismatches:
            lines.append(
                f"  model {p.appraisal.quantity} vs hand {p.item.label.quantity}  "
                f"{p.item.listing.name}"
            )

    if report.weak_resale_mismatches:
        lines.append(f"resale demand mismatches: {len(report.weak_resale_mismatches)}")
        for p in report.weak_resale_mismatches:
            lines.append(
                f"  model {p.appraisal.resale_demand} vs hand {p.item.label.resale_demand}  "
                f"{p.item.listing.name}"
            )

    if report.worst:
        lines.append("\nlargest disagreements (buy value, predicted vs hand):")
        for p in report.worst:
            predicted = policy.appraisal_buy_value(p.appraisal)
            actual = policy.appraisal_buy_value(p.item.label)
            lines.append(
                f"  {math.exp(abs(p.log_ratio)):>5.1f}x  ${predicted:>8.2f} vs ${actual:>8.2f}  "
                f"{p.item.listing.name}"
            )
            if p.appraisal.assumptions:
                lines.append(f"         model: {describe_appraisal(p.appraisal)}")
                lines.append(f"         hand:  {describe_appraisal(p.item.label)}")
    return "\n".join(lines)


# Each entry maps the full labeled set to predictions. Appraisers that learn from
# labels must be scored leave-one-out so they never see the item they predict.
def run_category_median(items: Sequence[LabeledItem], args: argparse.Namespace) -> Run:
    return Run(predict_leave_one_out(CategoryMedianAppraiser, items))


def run_claude(items: Sequence[LabeledItem], args: argparse.Namespace) -> Run:
    appraiser = ClaudeAppraiser(
        model=MODELS[args.model],
        use_images=not args.no_images,
        use_quantity=not args.no_quantity,
        cache_dir=args.cache_dir,
    )
    listings = [item.listing for item in items]
    misses = appraiser.uncached(listings)
    if misses:
        print(
            f"{appraiser.model_version}: {len(misses)} of {len(listings)} items need the API, "
            f"estimated cost up to ${appraiser.estimate_cost(misses):.3f}"
        )
        if not args.yes and input("Proceed? [y/N] ").strip().lower() != "y":
            raise SystemExit("Stopped; nothing was sent to the API.")
        load_dotenv(find_dotenv(usecwd=True))
    predictions, failures = predict_collecting_failures(appraiser, items)
    stored = appraiser.stored_cost(listings)
    per_item = stored / len(predictions) if predictions else 0.0
    notes = (
        f"model version: {appraiser.model_version}\n"
        f"cost: ${stored:.4f} for {len(predictions)} stored responses "
        f"(${per_item:.5f} per item); this run spent ${appraiser.spent_usd:.4f}"
    )
    return Run(predictions, failures, notes)


MODELS = {"haiku": claude.HAIKU, "sonnet": claude.SONNET, "opus": claude.OPUS}

APPRAISERS: dict[str, Callable[[Sequence[LabeledItem], argparse.Namespace], Run]] = {
    "category-median": run_category_median,
    "claude": run_claude,
}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=dataset.DEFAULT_PATH)
    parser.add_argument("--appraiser", choices=sorted(APPRAISERS), default="category-median")
    parser.add_argument("--worst", type=int, default=5, help="list the N largest disagreements")
    parser.add_argument("--limit", type=int, help="score only the first N items")
    parser.add_argument("--model", choices=sorted(MODELS), default="haiku", help="claude only")
    parser.add_argument("--no-images", action="store_true", help="claude: text only")
    parser.add_argument(
        "--no-quantity", action="store_true", help="claude: ask for one total, not quantity x unit"
    )
    parser.add_argument("--cache-dir", type=Path, default=claude.DEFAULT_CACHE_DIR)
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    args = parser.parse_args(argv)

    items = dataset.load(args.data)[: args.limit]
    print(f"{args.appraiser} on {len(items)} hand-valued items from {args.data}\n")
    run = APPRAISERS[args.appraiser](items, args)
    if run.notes:
        print(f"{run.notes}\n")
    if run.predictions:
        print(format_report(score(run.predictions, worst=args.worst)))
    if run.failures:
        print(f"\n{len(run.failures)} items failed and are not scored:")
        for failure in run.failures:
            print(f"  {failure.item.listing.name}: {failure.reason}")


if __name__ == "__main__":
    main()
