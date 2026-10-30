from pathlib import Path

import pytest

from item_appraiser import dataset, evaluate
from item_appraiser.baseline import CategoryMedianAppraiser
from item_appraiser.models import Appraisal, Condition, Confidence

FIXTURE = Path(__file__).parent / "fixtures" / "items.csv"


class EchoAppraiser:
    """Returns the hand label scaled by a constant factor."""

    def __init__(self, items, factor=1.0):
        self.labels = {i.listing.item_id: i.label for i in items}
        self.factor = factor

    def appraise(self, listing):
        label = self.labels[listing.item_id]
        return Appraisal(label.new_price_usd * self.factor, label.condition)


def test_perfect_appraiser_scores_perfectly():
    items = dataset.load(FIXTURE)
    report = evaluate.score(evaluate.predict(EchoAppraiser(items), items))
    assert report.buy_value.median_ratio_error == pytest.approx(1.0)
    assert report.buy_value.within_25_pct == 1.0
    assert report.buy_value.total_ratio == pytest.approx(1.0)
    assert report.loan_value.total_ratio == pytest.approx(1.0)
    assert report.condition_accuracy == 1.0


def test_doubling_appraiser_is_off_by_2x():
    items = dataset.load(FIXTURE)
    report = evaluate.score(evaluate.predict(EchoAppraiser(items, factor=2), items))
    assert report.new_price.median_ratio_error == pytest.approx(2.0)
    assert report.new_price.within_25_pct == 0
    assert report.new_price.within_2x == 1.0
    assert report.buy_value.total_ratio == pytest.approx(2.0)


def test_report_breaks_buy_value_down_by_confidence():
    items = dataset.load(FIXTURE)
    report = evaluate.score(evaluate.predict(EchoAppraiser(items), items))
    assert set(report.buy_value_by_confidence) == set(Confidence)
    assert all(s.n == 1 for s in report.buy_value_by_confidence.values())


def test_zero_estimate_is_a_large_finite_miss():
    items = dataset.load(FIXTURE)
    report = evaluate.score(evaluate.predict(EchoAppraiser(items, factor=0), items))
    assert report.buy_value.within_2x == 0
    assert report.buy_value.median_ratio_error > 100


def test_leave_one_out_never_sees_the_predicted_item():
    items = dataset.load(FIXTURE)
    seen = []

    def build(training):
        seen.append({i.listing.item_id for i in training})
        return CategoryMedianAppraiser(training)

    predictions = evaluate.predict_leave_one_out(build, items)
    for prediction, training_ids in zip(predictions, seen):
        assert prediction.item.listing.item_id not in training_ids
        assert len(training_ids) == len(items) - 1


def test_category_median_falls_back_to_overall_median():
    items = dataset.load(FIXTURE)
    appraiser = CategoryMedianAppraiser(items[:2])  # tools only
    toy = items[2].listing
    assert appraiser.appraise(toy).new_price_usd == 85  # median of 150 and 20
    assert appraiser.appraise(items[0].listing).condition == Condition.USED


def test_main_prints_a_report(capsys):
    evaluate.main(["--data", str(FIXTURE), "--worst", "2"])
    out = capsys.readouterr().out
    assert "category-median on 3 hand-valued items" in out
    assert "largest disagreements" in out
