import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

from item_appraiser import claude, dataset, evaluate, policy, prompt
from item_appraiser.claude import ClaudeAppraiser
from item_appraiser.climate import PRICE_YEAR_ADJUSTMENT
from item_appraiser.models import (
    AppraisalError,
    Condition,
    Confidence,
    FootprintCategory,
    Impact,
    Listing,
    ResaleDemand,
)

FIXTURE = Path(__file__).parent / "fixtures" / "items.csv"

LISTING = Listing(
    name="Garden gnome",
    description="Slightly chipped",
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
    assert result.assumption == OUTPUT["assumption"]
    assert result.model_version == "claude-sonnet-5-5/p4+img+qty"


def test_new_price_is_rounded_to_cents(tmp_path):
    client = FakeClient(message({**OUTPUT, "quantity": 3, "unit_new_price_usd": 19.99}))
    assert appraiser(tmp_path, client).appraise(LISTING).new_price_usd == 59.97


def test_appraisal_reads_weak_resale_demand_and_policy_applies_it(tmp_path):
    client = FakeClient(message({**OUTPUT, "resale_demand": "weak"}))
    result = appraiser(tmp_path, client).appraise(LISTING)
    assert result.resale_demand == ResaleDemand.WEAK
    assert policy.appraisal_buy_value(result) == pytest.approx(37.5 * 0.25, abs=0.01)
    assert "resale_demand" in client.requests[0]["output_config"]["format"]["schema"]["required"]


def test_no_quantity_arm_reads_a_total_and_asks_for_one(tmp_path):
    client = FakeClient(
        message(
            {k: v for k, v in OUTPUT.items() if k not in ("quantity", "unit_new_price_usd")}
            | {"new_price_usd": 40.0}
        )
    )
    result = appraiser(tmp_path, client, use_quantity=False).appraise(LISTING)
    assert result.new_price_usd == 40
    assert result.quantity is None
    assert result.model_version == "claude-sonnet-5-5/p4+img+total"
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
        {"model": claude.HAIKU},
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
    monkeypatch.setattr(prompt, "PROMPT_INTRO", prompt.PROMPT_INTRO + "One more rule.\n")
    assert appraiser(tmp_path).uncached([LISTING]) == [LISTING]


def test_editing_the_listing_text_misses_the_cache(tmp_path, monkeypatch):
    appraiser(tmp_path).appraise(LISTING)
    original = prompt.listing_text
    monkeypatch.setattr(prompt, "listing_text", lambda *a: original(*a) + "\nMore context")
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

    response = SimpleNamespace(request=request, status_code=401, headers={"request-id": "req_test"})
    denied = anthropic.AuthenticationError("bad key", response=response, body=None)
    with pytest.raises(anthropic.AuthenticationError):
        appraiser(tmp_path, FakeClient(denied)).appraise(LISTING)


def test_cost_counts_cache_reads_at_their_own_rate(tmp_path):
    a = appraiser(tmp_path)
    a.appraise(LISTING)
    expected = (1000 * 2.00 + 200 * 10.00 + 2000 * 0.20) / 1_000_000
    assert a.spent_usd == pytest.approx(expected)
    assert a.stored_cost([LISTING]) == pytest.approx(expected)


def test_estimate_scales_with_photos_and_model(tmp_path):
    sonnet = appraiser(tmp_path)
    assert sonnet.estimate_cost([LISTING]) > appraiser(tmp_path, use_images=False).estimate_cost(
        [LISTING]
    )
    assert appraiser(tmp_path, model=claude.HAIKU).estimate_cost([LISTING]) == pytest.approx(
        sonnet.estimate_cost([LISTING]) / 20
    )


def test_unpriced_model_works_without_cost_tracking(tmp_path):
    a = appraiser(tmp_path, model="claude-unknown")
    assert a.appraise(LISTING).model_version.startswith("claude-unknown/")
    assert a.spent_usd == 0
    with pytest.raises(ValueError, match="price="):
        a.estimate_cost([LISTING])


def test_unpriced_model_tracks_costs_with_a_given_price(tmp_path):
    a = appraiser(tmp_path, model="claude-unknown", price=claude.PRICES[claude.SONNET])
    a.appraise(LISTING)
    assert a.spent_usd == pytest.approx((1000 * 2.00 + 200 * 10.00 + 2000 * 0.20) / 1_000_000)


def test_appraisal_carries_the_fingerprint_of_its_listing(tmp_path):
    a = appraiser(tmp_path)
    fresh = a.appraise(LISTING)
    cached = a.appraise(LISTING)
    assert fresh.fingerprint == cached.fingerprint == a.fingerprint(LISTING)
    assert len(fresh.fingerprint) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Garden gnomes"},
        {"description": "Badly chipped"},
        {"image_urls": ("https://example.com/other.jpg",)},
    ],
)
def test_editing_the_listing_changes_its_fingerprint(tmp_path, change):
    a = appraiser(tmp_path)
    edited = Listing(**{**vars(LISTING), **change})
    assert a.fingerprint(edited) != a.fingerprint(LISTING)


def test_item_id_and_model_settings_affect_the_fingerprint_as_expected(tmp_path):
    a = appraiser(tmp_path)
    assert a.fingerprint(Listing(**{**vars(LISTING), "item_id": "x"})) == a.fingerprint(LISTING)
    assert appraiser(tmp_path, model=claude.HAIKU).fingerprint(LISTING) != a.fingerprint(LISTING)
    assert appraiser(tmp_path, use_images=False).fingerprint(LISTING) != a.fingerprint(LISTING)
    climate_output = {**OUTPUT, "footprint_category": "plastic household goods"}
    climate = appraiser(tmp_path, FakeClient(message(climate_output)), impacts=["money", "climate"])
    assert climate.fingerprint(LISTING) != a.fingerprint(LISTING)
    assert climate.appraise(LISTING).fingerprint == climate.fingerprint(LISTING)


def test_prompts_differ_only_in_the_quantity_section():
    with_quantity = prompt.system_prompt(True)
    total = prompt.system_prompt(False)
    assert with_quantity != total
    assert with_quantity.startswith(prompt.PROMPT_INTRO)
    assert total.endswith(prompt.PROMPT_OUTRO)


class TestEvaluateMain:
    @pytest.fixture
    def fake_api(self, monkeypatch):
        client = FakeClient()
        monkeypatch.setattr(claude.anthropic, "Anthropic", lambda: client)
        monkeypatch.setattr(claude, "image_is_reachable", lambda url: True)
        monkeypatch.setattr(evaluate, "load_dotenv", lambda: None)
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
        assert "claude-sonnet-5-5/p4+img+qty" in out
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
    report = evaluate.score(
        evaluate.predict_leave_one_out(lambda t: evaluate.CategoryMedianAppraiser(t, {}), items)
    )
    assert [p.item.listing.item_id for p in report.weak_resale_mismatches] == ["a3"]
    assert "resale demand mismatches: 1" in evaluate.format_report(report)


def test_quantity_scoring_skips_unlabeled_items_and_baselines():
    items = dataset.load(FIXTURE)
    report = evaluate.score(
        evaluate.predict_leave_one_out(lambda t: evaluate.CategoryMedianAppraiser(t, {}), items)
    )
    assert report.quantity is None


def test_without_a_cache_dir_every_appraisal_calls_the_api(tmp_path):
    client = FakeClient()
    a = ClaudeAppraiser(client=client, image_check=lambda url: True)
    a.appraise(LISTING)
    a.appraise(LISTING)
    assert len(client.requests) == 2
    assert a.uncached([LISTING]) == [LISTING]
    assert a.stored_cost([LISTING]) == 0
    assert not any(tmp_path.iterdir())


def test_listing_text_sends_only_name_photos_and_description():
    text = prompt.listing_text(LISTING, 2)
    assert text.splitlines() == [
        "<listing>",
        "Name: Garden gnome",
        "Photos: 2 attached",
        "Description: Slightly chipped",
        "</listing>",
    ]


def test_missing_anthropic_package_gives_an_install_hint(monkeypatch):
    monkeypatch.setattr(claude, "anthropic", None)
    with pytest.raises(ImportError, match=r"item-appraiser\[claude\]"):
        ClaudeAppraiser()


def test_injected_client_works_without_the_anthropic_package(tmp_path, monkeypatch):
    monkeypatch.setattr(claude, "anthropic", None)
    assert appraiser(tmp_path).appraise(LISTING).new_price_usd == 37.5


CLIMATE_OUTPUT = {**OUTPUT, "footprint_category": "plastic household goods"}


def test_money_only_is_the_default_and_asks_for_no_footprint(tmp_path):
    client = FakeClient()
    result = appraiser(tmp_path, client).appraise(LISTING)
    request = client.requests[0]
    assert "footprint_category" not in request["output_config"]["format"]["schema"]["properties"]
    assert "Footprint category" not in request["system"][0]["text"]
    assert result.footprint_category is None
    assert result.impacts == {Impact.MONEY}
    assert result.new_item_kg_co2e is None


def test_climate_adds_a_footprint_category_to_the_same_call(tmp_path):
    client = FakeClient(message(CLIMATE_OUTPUT))
    result = appraiser(tmp_path, client, impacts=["money", "climate"]).appraise(LISTING)
    assert len(client.requests) == 1
    request = client.requests[0]
    schema = request["output_config"]["format"]["schema"]
    assert list(schema["properties"])[:2] == ["assumption", "footprint_category"]
    assert "footprint_category" in schema["required"]
    assert set(schema["properties"]["footprint_category"]["enum"]) == {
        c.value for c in FootprintCategory
    }
    assert request["system"][0]["text"].startswith(prompt.system_prompt(True))
    assert "Footprint category." in request["system"][0]["text"]
    assert result.footprint_category == FootprintCategory.PLASTIC_GOODS
    assert result.model_version == "claude-sonnet-5-5/p4+img+qty+co2-f1"
    assert result.new_item_kg_co2e == round(37.5 * PRICE_YEAR_ADJUSTMENT * 0.332, 1)
    assert result.buy_value_usd == 22.5


def test_climate_only_still_estimates_price_but_reports_only_climate(tmp_path):
    client = FakeClient(message(CLIMATE_OUTPUT))
    result = appraiser(tmp_path, client, impacts=[Impact.CLIMATE]).appraise(LISTING)
    data = result.to_dict()
    assert data["impacts"] == ["climate"]
    assert "buy_value_usd" not in data
    assert data["new_item_kg_co2e"] == result.new_item_kg_co2e
    assert data["giveaway_kg_co2e"] == result.giveaway_kg_co2e
    assert data["loan_kg_co2e"] == result.loan_kg_co2e


def test_money_only_cache_key_is_unchanged_so_old_responses_still_hit(tmp_path):
    key = appraiser(tmp_path)._cache_key(LISTING)
    assert set(key) == {
        "model",
        "prompt_version",
        "effort",
        "system",
        "schema",
        "image_urls",
        "text",
    }


def test_adding_climate_misses_the_money_only_cache(tmp_path):
    appraiser(tmp_path).appraise(LISTING)
    assert appraiser(tmp_path, impacts=["money", "climate"]).uncached([LISTING]) == [LISTING]


def test_unknown_footprint_category_fails_and_is_not_cached(tmp_path):
    client = FakeClient(message({**OUTPUT, "footprint_category": "spaceships"}))
    a = appraiser(tmp_path, client, impacts=["climate"])
    with pytest.raises(AppraisalError):
        a.appraise(LISTING)
    assert a.uncached([LISTING]) == [LISTING]


@pytest.mark.parametrize("impacts", [[], ["carbon"], "climate"])
def test_bad_impacts_are_rejected(tmp_path, impacts):
    with pytest.raises((ValueError, TypeError)):
        appraiser(tmp_path, impacts=impacts)


def test_climate_prompt_costs_more_to_estimate(tmp_path):
    money = appraiser(tmp_path).estimate_cost([LISTING])
    both = appraiser(tmp_path, impacts=["money", "climate"]).estimate_cost([LISTING])
    assert both > money


class TestEvaluateClimate:
    @pytest.fixture
    def fake_api(self, monkeypatch):
        client = FakeClient(*[message(CLIMATE_OUTPUT) for _ in range(4)])
        monkeypatch.setattr(claude.anthropic, "Anthropic", lambda: client)
        monkeypatch.setattr(claude, "image_is_reachable", lambda url: True)
        monkeypatch.setattr(evaluate, "load_dotenv", lambda: None)
        return client

    def run(self, tmp_path, *extra):
        evaluate.main(
            ["--data", str(FIXTURE), "--appraiser", "claude", "--cache-dir", str(tmp_path), *extra]
        )

    def test_climate_run_adds_an_unscored_summary(self, tmp_path, fake_api, capsys):
        self.run(tmp_path, "--yes", "--impacts", "money,climate")
        out = capsys.readouterr().out
        assert "buy value" in out
        assert "climate impact, 3 items (unscored; no hand labels)" in out
        assert "   3  100%  plastic household goods" in out
        assert "largest new-item footprints" in out

    def test_unlabeled_appraises_every_row_and_skips_scoring(self, tmp_path, fake_api, capsys):
        self.run(tmp_path, "--yes", "--impacts", "climate", "--unlabeled")
        out = capsys.readouterr().out
        assert "claude on 4 listings" in out  # includes the row not yet valued
        assert "climate impact, 4 items" in out
        assert "typical error" not in out
        assert len(fake_api.requests) == 4

    def test_unlabeled_needs_climate(self, tmp_path, fake_api):
        with pytest.raises(SystemExit):
            self.run(tmp_path, "--yes", "--unlabeled")

    def test_bad_impacts_flag_is_a_usage_error(self, tmp_path, fake_api):
        with pytest.raises(SystemExit):
            self.run(tmp_path, "--impacts", "carbon")
