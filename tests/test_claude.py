import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

from item_appraiser import claude, dataset, evaluate, policy
from item_appraiser.claude import AppraisalError, ClaudeAppraiser
from item_appraiser.models import Condition, Confidence, Listing, ResaleDemand

FIXTURE = Path(__file__).parent / "fixtures" / "items.csv"

LISTING = Listing(
    name="Garden gnome",
    description="Slightly chipped",
    category="Home & Garden",
    tags=("garden", "decor"),
    image_urls=("https://example.com/live.jpg", "https://example.com/dead.jpg"),
)
OUTPUT = {
    "assumption": "Priced as a mid-size resin gnome.",
    "quantity": 3,
    "unit_new_price_usd": 12.5,
    "condition": "used",
    "resale_demand": "typical",
    "confidence": "medium",
}


def message(output=OUTPUT, stop_reason="end_turn"):
    body = {
        "content": [
            {"type": "thinking", "thinking": "", "signature": "x"},
            {"type": "text", "text": json.dumps(output)},
        ],
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 2000,
        },
    }
    return SimpleNamespace(model_dump=lambda mode: body)


class FakeClient:
    def __init__(self, *responses):
        self.requests = []
        self.responses = list(responses)
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        response = self.responses.pop(0) if self.responses else message()
        if isinstance(response, Exception):
            raise response
        return response


def appraiser(tmp_path, client=None, **kwargs):
    kwargs.setdefault("image_check", lambda url: "dead" not in url)
    return ClaudeAppraiser(cache_dir=tmp_path, client=client or FakeClient(), **kwargs)


def test_appraisal_multiplies_quantity_by_unit_price(tmp_path):
    result = appraiser(tmp_path).appraise(LISTING)
    assert result.new_price_usd == 37.5
    assert result.quantity == 3
    assert result.unit_new_price_usd == 12.5
    assert result.condition == Condition.USED
    assert result.confidence == Confidence.MEDIUM
    assert result.assumptions == OUTPUT["assumption"]
    assert result.method == "claude"
    assert result.model_version == "claude-haiku-5-5/p3+img+qty"


def test_appraisal_reads_weak_resale_demand_and_policy_applies_it(tmp_path):
    client = FakeClient(message({**OUTPUT, "resale_demand": "weak"}))
    result = appraiser(tmp_path, client).appraise(LISTING)
    assert result.resale_demand == ResaleDemand.WEAK
    assert policy.appraisal_buy_value(result) == pytest.approx(37.5 * 0.25, abs=0.01)
    assert "resale_demand" in client.requests[0]["output_config"]["format"]["schema"]["required"]


def test_no_quantity_arm_reads_a_total_and_asks_for_one(tmp_path):
    client = FakeClient(
        message({k: v for k, v in OUTPUT.items() if k not in ("quantity", "unit_new_price_usd")}
                | {"new_price_usd": 40.0})
    )
    result = appraiser(tmp_path, client, use_quantity=False).appraise(LISTING)
    assert result.new_price_usd == 40
    assert result.quantity is None
    assert result.model_version == "claude-haiku-5-5/p3+img+total"
    schema = client.requests[0]["output_config"]["format"]["schema"]
    assert "new_price_usd" in schema["properties"]
    assert "quantity" not in schema["properties"]


def test_request_sends_reachable_photos_before_the_text_and_caches_the_system_prompt(tmp_path):
    client = FakeClient()
    appraiser(tmp_path, client).appraise(LISTING)
    request = client.requests[0]
    content = request["messages"][0]["content"]
    assert [block["type"] for block in content] == ["image", "text"]
    assert content[0]["source"] == {"type": "url", "url": "https://example.com/live.jpg"}
    assert "Photos: 1 attached" in content[1]["text"]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["output_config"]["effort"] == claude.EFFORT
    assert "temperature" not in request


def test_text_only_arm_sends_no_photos_and_checks_no_urls(tmp_path):
    def no_check(url):
        raise AssertionError("text-only runs should not check photo URLs")

    client = FakeClient()
    appraiser(tmp_path, client, use_images=False, image_check=no_check).appraise(LISTING)
    content = client.requests[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["text"]
    assert "Photos: none provided" in content[0]["text"]


def test_second_appraisal_comes_from_the_cache(tmp_path):
    client = FakeClient()
    first = appraiser(tmp_path, client).appraise(LISTING)
    second = appraiser(tmp_path, client).appraise(LISTING)
    assert len(client.requests) == 1
    assert second == first


def test_cache_hit_needs_no_client(tmp_path):
    appraiser(tmp_path).appraise(LISTING)
    offline = ClaudeAppraiser(cache_dir=tmp_path, image_check=lambda url: True)
    assert offline.appraise(LISTING).new_price_usd == 37.5
    assert offline._client is None


@pytest.mark.parametrize(
    "change",
    [
        {"model": claude.SONNET},
        {"use_images": False},
        {"use_quantity": False},
    ],
)
def test_changing_the_arm_misses_the_cache(tmp_path, change):
    appraiser(tmp_path).appraise(LISTING)
    assert appraiser(tmp_path, **change).uncached([LISTING]) == [LISTING]


def test_changing_the_listing_misses_the_cache(tmp_path):
    a = appraiser(tmp_path)
    a.appraise(LISTING)
    changed = Listing(name=LISTING.name, description="Brand new", image_urls=LISTING.image_urls)
    assert a.uncached([LISTING, changed]) == [changed]


def test_editing_the_prompt_misses_the_cache(tmp_path, monkeypatch):
    appraiser(tmp_path).appraise(LISTING)
    monkeypatch.setattr(claude, "PROMPT_INTRO", claude.PROMPT_INTRO + "One more rule.\n")
    assert appraiser(tmp_path).uncached([LISTING]) == [LISTING]


@pytest.mark.parametrize(
    "response",
    [
        message(stop_reason="refusal"),
        message(stop_reason="max_tokens"),
        message({**OUTPUT, "quantity": 0}),
        message({**OUTPUT, "unit_new_price_usd": -1}),
        message({**OUTPUT, "condition": "gently loved"}),
        message({**OUTPUT, "resale_demand": "unknown"}),
        message({k: v for k, v in OUTPUT.items() if k != "condition"}),
    ],
)
def test_unusable_responses_fail_and_are_retried_rather_than_cached(tmp_path, response):
    client = FakeClient(response)
    a = appraiser(tmp_path, client)
    with pytest.raises(AppraisalError):
        a.appraise(LISTING)
    assert a.uncached([LISTING]) == [LISTING]
    assert a.appraise(LISTING).new_price_usd == 37.5


def test_api_errors_fail_the_item_but_auth_errors_stop_the_run(tmp_path):
    request = SimpleNamespace(method="POST", url="https://example.com")
    unreachable = anthropic.APIConnectionError(request=request)
    with pytest.raises(AppraisalError):
        appraiser(tmp_path, FakeClient(unreachable)).appraise(LISTING)

    response = SimpleNamespace(
        request=request, status_code=401, headers={"request-id": "req_test"}
    )
    denied = anthropic.AuthenticationError("bad key", response=response, body=None)
    with pytest.raises(anthropic.AuthenticationError):
        appraiser(tmp_path, FakeClient(denied)).appraise(LISTING)


def test_cost_counts_cache_reads_at_their_own_rate(tmp_path):
    a = appraiser(tmp_path)
    a.appraise(LISTING)
    expected = (1000 * 0.10 + 200 * 0.50 + 2000 * 0.01) / 1_000_000
    assert a.spent_usd == pytest.approx(expected)
    assert a.stored_cost([LISTING]) == pytest.approx(expected)


def test_estimate_scales_with_photos_and_model(tmp_path):
    haiku = appraiser(tmp_path)
    assert haiku.estimate_cost([LISTING]) > appraiser(tmp_path, use_images=False).estimate_cost(
        [LISTING]
    )
    assert appraiser(tmp_path, model=claude.SONNET).estimate_cost(
        [LISTING]
    ) == pytest.approx(haiku.estimate_cost([LISTING]) * 20)


def test_unpriced_model_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        appraiser(tmp_path, model="claude-unknown")


def test_prompts_differ_only_in_the_quantity_section():
    with_quantity = claude.system_prompt(True)
    total = claude.system_prompt(False)
    assert with_quantity != total
    assert with_quantity.startswith(claude.PROMPT_INTRO)
    assert total.endswith(claude.PROMPT_OUTRO)


class TestEvaluateMain:
    @pytest.fixture
    def fake_api(self, monkeypatch):
        client = FakeClient()
        monkeypatch.setattr(claude.anthropic, "Anthropic", lambda: client)
        monkeypatch.setattr(claude, "image_is_reachable", lambda url: True)
        monkeypatch.setattr(evaluate, "load_dotenv", lambda *a: None)
        return client

    def run(self, tmp_path, *extra):
        evaluate.main(
            ["--data", str(FIXTURE), "--appraiser", "claude", "--cache-dir", str(tmp_path), *extra]
        )

    def test_declining_the_estimate_sends_nothing(self, tmp_path, fake_api, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda prompt: "n")
        with pytest.raises(SystemExit):
            self.run(tmp_path)
        assert "estimated cost" in capsys.readouterr().out
        assert fake_api.requests == []

    def test_yes_runs_and_reports_cost_quantity_and_model_confidence(
        self, tmp_path, fake_api, capsys
    ):
        self.run(tmp_path, "--yes")
        out = capsys.readouterr().out
        assert "estimated cost" in out
        assert "claude-haiku-5-5/p3+img+qty" in out
        assert "per item" in out
        assert "buy, model medium" in out
        assert "quantity accuracy: 0% of 2 (2 overcounted, 0 undercounted)" in out
        assert "model: 3 x $12.50 new, used, medium conf.: Priced as a mid-size" in out
        assert len(fake_api.requests) == 3

    def test_rerun_costs_nothing_and_prints_no_estimate(self, tmp_path, fake_api, capsys):
        self.run(tmp_path, "--yes")
        capsys.readouterr()
        self.run(tmp_path)  # no --yes: a prompt here would fail under pytest
        out = capsys.readouterr().out
        assert "estimated cost" not in out
        assert "this run spent $0.0000" in out
        assert len(fake_api.requests) == 3

    def test_limit_scores_only_the_first_items(self, tmp_path, fake_api, capsys):
        self.run(tmp_path, "--yes", "--limit", "1")
        assert "on 1 hand-valued items" in capsys.readouterr().out
        assert len(fake_api.requests) == 1

    def test_failed_items_are_listed_and_the_rest_still_scored(self, tmp_path, fake_api, capsys):
        fake_api.responses = [message(stop_reason="refusal")]
        self.run(tmp_path, "--yes")
        out = capsys.readouterr().out
        assert "1 items failed and are not scored" in out
        assert "stopped early: refusal" in out
        assert "buy value" in out


def test_labels_carry_quantity_where_filled_in():
    items = dataset.load(FIXTURE)
    assert [i.label.quantity for i in items] == [1, None, 2]


def test_labels_carry_resale_demand_defaulting_to_typical():
    items = dataset.load(FIXTURE)
    assert [i.label.resale_demand for i in items] == [
        ResaleDemand.TYPICAL,
        ResaleDemand.TYPICAL,
        ResaleDemand.WEAK,
    ]


def test_report_lists_resale_demand_mismatches():
    items = dataset.load(FIXTURE)
    report = evaluate.score(evaluate.predict_leave_one_out(evaluate.CategoryMedianAppraiser, items))
    assert [p.item.listing.item_id for p in report.weak_resale_mismatches] == ["a3"]
    assert "resale demand mismatches: 1" in evaluate.format_report(report)


def test_quantity_scoring_skips_unlabeled_items_and_baselines():
    items = dataset.load(FIXTURE)
    report = evaluate.score(evaluate.predict_leave_one_out(evaluate.CategoryMedianAppraiser, items))
    assert report.quantity is None
