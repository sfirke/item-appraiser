import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest

from item_appraiser import deepseek, evaluate, prompt
from item_appraiser.deepseek import DeepSeekAppraiser
from item_appraiser.models import (
    Appraisal,
    AppraisalError,
    Condition,
    FootprintCategory,
    Listing,
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
USAGE = {
    "prompt_tokens": 3000,
    "completion_tokens": 200,
    "prompt_cache_hit_tokens": 2000,
    "prompt_cache_miss_tokens": 1000,
}


def completion(output=OUTPUT, finish_reason="stop", content=None, fingerprint="fp_a"):
    body = {
        "model": "deepseek-flash",
        "system_fingerprint": fingerprint,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "reasoning_content": "Thinking about gnomes.",
                    "content": json.dumps(output) if content is None else content,
                },
            }
        ],
        "usage": USAGE,
    }
    return SimpleNamespace(model_dump=lambda mode: body)


class FakeClient:
    def __init__(self, *responses):
        self.requests = []
        self.responses = list(responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        response = self.responses.pop(0) if self.responses else completion()
        if isinstance(response, Exception):
            raise response
        return response


def appraiser(tmp_path, client=None, **kwargs):
    kwargs.setdefault("image_check", lambda url: "dead" not in url)
    return DeepSeekAppraiser(cache_dir=tmp_path, client=client or FakeClient(), **kwargs)


def test_appraisal_multiplies_quantity_by_unit_price(tmp_path):
    result = appraiser(tmp_path).appraise(LISTING)
    assert result.new_price_usd == 37.5
    assert result.quantity == 3
    assert result.condition == Condition.USED
    assert result.method == "deepseek"
    assert result.model_version == "deepseek-flash/p4+img+qty"


def test_appraisal_carries_the_backend_fingerprint_through_the_cache(tmp_path):
    first = appraiser(tmp_path).appraise(LISTING)
    assert first.model_fingerprint == "fp_a"
    assert first.to_dict()["model_fingerprint"] == "fp_a"
    assert appraiser(tmp_path).appraise(LISTING).model_fingerprint == "fp_a"


def test_missing_fingerprint_is_none(tmp_path):
    client = FakeClient(completion(fingerprint=None))
    assert appraiser(tmp_path, client).appraise(LISTING).model_fingerprint is None


def test_fingerprint_note():
    def a(fingerprint):
        return Appraisal(10, Condition.USED, model_fingerprint=fingerprint)

    assert evaluate.fingerprint_note([a(None), a(None)]) == ""
    assert evaluate.fingerprint_note([a("fp_a"), a("fp_a")]) == "\nmodel fingerprint: fp_a"
    mixed = evaluate.fingerprint_note([a("fp_a"), a("fp_b"), a("fp_a")])
    assert "WARNING: answers came from 2 model fingerprints" in mixed
    assert "   2  fp_a" in mixed
    assert "   1  fp_b" in mixed


def test_request_uses_json_mode_low_effort_and_reachable_photos_first(tmp_path):
    client = FakeClient()
    appraiser(tmp_path, client).appraise(LISTING)
    request = client.requests[0]
    assert request["model"] == "deepseek-flash"
    assert request["response_format"] == {"type": "json_object"}
    assert request["reasoning_effort"] == "low"
    system, user = request["messages"]
    assert system["role"] == "system"
    # The tested prompt, then the schema spelled out, since JSON mode doesn't enforce one.
    assert system["content"].startswith(prompt.system_prompt())
    assert "JSON" in system["content"]
    assert json.dumps(prompt.output_schema()) in system["content"]
    assert [part["type"] for part in user["content"]] == ["image_url", "text"]
    assert user["content"][0]["image_url"] == {"url": "https://example.com/live.jpg"}
    assert "Photos: 1 attached" in user["content"][1]["text"]


def test_text_only_and_total_arms(tmp_path):
    client = FakeClient(
        completion(
            {k: v for k, v in OUTPUT.items() if k not in ("quantity", "unit_new_price_usd")}
            | {"new_price_usd": 40}
        )
    )
    result = appraiser(tmp_path, client, use_images=False, use_quantity=False).appraise(LISTING)
    assert result.new_price_usd == 40
    assert result.model_version == "deepseek-flash/p4+text+total"
    assert [p["type"] for p in client.requests[0]["messages"][1]["content"]] == ["text"]


def test_climate_asks_for_and_reads_a_footprint_category(tmp_path):
    client = FakeClient(completion({**OUTPUT, "footprint_category": "plastic household goods"}))
    result = appraiser(tmp_path, client, impacts=["money", "climate"]).appraise(LISTING)
    assert "footprint_category" in client.requests[0]["messages"][0]["content"]
    assert result.footprint_category == FootprintCategory.PLASTIC_GOODS
    assert result.model_version == "deepseek-flash/p4+img+qty+co2-f1"


def test_second_appraisal_comes_from_the_cache_without_a_client_or_key(tmp_path, monkeypatch):
    first = appraiser(tmp_path).appraise(LISTING)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    offline = DeepSeekAppraiser(cache_dir=tmp_path, image_check=lambda url: "dead" not in url)
    assert offline.appraise(LISTING) == first
    assert offline._client is None


def test_cache_is_separate_from_claudes(tmp_path):
    from item_appraiser.claude import ClaudeAppraiser

    appraiser(tmp_path).appraise(LISTING)
    claude = ClaudeAppraiser(cache_dir=tmp_path, client=object(), image_check=lambda url: True)
    assert claude.uncached([LISTING]) == [LISTING]


@pytest.mark.parametrize("change", [{"use_images": False}, {"use_quantity": False}])
def test_changing_the_arm_misses_the_cache(tmp_path, change):
    appraiser(tmp_path).appraise(LISTING)
    assert appraiser(tmp_path, **change).uncached([LISTING]) == [LISTING]


@pytest.mark.parametrize(
    "response",
    [
        completion(finish_reason="length"),
        completion(finish_reason="content_filter"),
        completion(content="   "),  # what DeepSeek returns when the answer wasn't valid JSON
        completion(content='{"assumption": "cut off'),
        completion(content="[1, 2]"),
        completion({**OUTPUT, "quantity": 2.5}),
        completion({**OUTPUT, "quantity": "3"}),
        completion({**OUTPUT, "unit_new_price_usd": "12.50"}),
        completion({**OUTPUT, "unit_new_price_usd": True}),
        completion({**OUTPUT, "condition": "Used"}),
        completion({**OUTPUT, "notes": "extra key"}),
        completion({k: v for k, v in OUTPUT.items() if k != "confidence"}),
        completion({**OUTPUT, "quantity": 0}),
        SimpleNamespace(model_dump=lambda mode: {"choices": [], "usage": USAGE}),
    ],
)
def test_unusable_responses_fail_and_are_retried_rather_than_cached(tmp_path, response):
    client = FakeClient(response)
    a = appraiser(tmp_path, client)
    with pytest.raises(AppraisalError):
        a.appraise(LISTING)
    assert a.uncached([LISTING]) == [LISTING]
    assert a.appraise(LISTING).new_price_usd == 37.5


def test_whole_number_float_price_is_accepted(tmp_path):
    client = FakeClient(completion({**OUTPUT, "unit_new_price_usd": 12}))
    assert appraiser(tmp_path, client).appraise(LISTING).new_price_usd == 36


REQUEST = SimpleNamespace(method="POST", url="https://api.deepseek.com/chat/completions")


def api_error(cls, status):
    response = SimpleNamespace(request=REQUEST, status_code=status, headers={})
    return cls("nope", response=response, body=None)


def test_api_errors_fail_the_item_but_auth_errors_stop_the_run(tmp_path):
    for error in (
        openai.APIConnectionError(request=REQUEST),
        openai.APITimeoutError(request=REQUEST),
        api_error(openai.BadRequestError, 400),
        api_error(openai.UnprocessableEntityError, 422),
        api_error(openai.RateLimitError, 429),
        api_error(openai.InternalServerError, 503),
    ):
        with pytest.raises(AppraisalError):
            appraiser(tmp_path, FakeClient(error)).appraise(LISTING)
    for error in (
        api_error(openai.AuthenticationError, 401),
        api_error(openai.PermissionDeniedError, 403),
    ):
        with pytest.raises(type(error)):
            appraiser(tmp_path, FakeClient(error)).appraise(LISTING)


def test_missing_key_fails_clearly_instead_of_sending_another_providers_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    a = DeepSeekAppraiser(cache_dir=tmp_path, image_check=lambda url: True)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        a.appraise(LISTING)


def test_client_from_the_environment_points_at_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    client = DeepSeekAppraiser().client
    assert client.api_key == "sk-deepseek"
    assert str(client.base_url).rstrip("/") == deepseek.BASE_URL


def test_peak_hours():
    assert deepseek.is_peak(datetime(2026, 11, 5, 2, 30, tzinfo=UTC))  # Thursday
    assert deepseek.is_peak(datetime(2026, 11, 5, 9, 59, tzinfo=UTC))
    assert not deepseek.is_peak(datetime(2026, 11, 5, 4, 0, tzinfo=UTC))
    assert not deepseek.is_peak(datetime(2026, 11, 5, 10, 0, tzinfo=UTC))
    assert not deepseek.is_peak(datetime(2026, 11, 7, 2, 30, tzinfo=UTC))  # Saturday


def test_cost_counts_cache_hits_and_halves_off_peak():
    price = deepseek.PRICES[deepseek.FLASH]
    peak = (1000 * price.input + 2000 * price.cache_read + 200 * price.output) / 1_000_000
    thursday = datetime(2026, 11, 5, 2, tzinfo=UTC)
    saturday = datetime(2026, 11, 7, 2, tzinfo=UTC)
    assert deepseek.usage_cost(USAGE, price, thursday) == pytest.approx(peak)
    assert deepseek.usage_cost(USAGE, price, saturday) == pytest.approx(peak / 2)


def test_spent_and_stored_cost_agree(tmp_path):
    a = appraiser(tmp_path)
    a.appraise(LISTING)
    assert a.spent_usd > 0
    assert a.stored_cost([LISTING]) == pytest.approx(a.spent_usd)


def test_estimate_scales_with_photos(tmp_path):
    with_photos = appraiser(tmp_path).estimate_cost([LISTING])
    assert with_photos > appraiser(tmp_path, use_images=False).estimate_cost([LISTING]) > 0


def test_unpriced_model_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        appraiser(tmp_path, model="deepseek-v4-pro")


def test_missing_openai_package_gives_an_install_hint(monkeypatch):
    monkeypatch.setattr(deepseek, "openai", None)
    with pytest.raises(ImportError, match=r"item-appraiser\[deepseek\]"):
        DeepSeekAppraiser()


def test_injected_client_works_without_the_openai_package(tmp_path, monkeypatch):
    monkeypatch.setattr(deepseek, "openai", None)
    assert appraiser(tmp_path).appraise(LISTING).new_price_usd == 37.5


class TestEvaluateMain:
    @pytest.fixture
    def fake_api(self, monkeypatch):
        client = FakeClient()
        monkeypatch.setattr(deepseek.DeepSeekAppraiser, "client", property(lambda self: client))
        monkeypatch.setattr(deepseek, "image_is_reachable", lambda url: True)
        monkeypatch.setattr(evaluate, "load_dotenv", lambda: None)
        return client

    def run(self, *args):
        evaluate.main(["--data", str(FIXTURE), "--appraiser", "deepseek", *args])

    def test_runs_scores_and_caches_under_its_own_name(
        self, tmp_path, fake_api, capsys, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        self.run("--yes")
        out = capsys.readouterr().out
        assert "deepseek-flash/p4+img+qty" in out
        assert "buy value" in out
        assert len(fake_api.requests) == 3
        assert len(list((tmp_path / "data" / "cache" / "deepseek").iterdir())) == 3

        self.run()  # no --yes: a cost prompt here would fail under pytest
        assert "this run spent $0.0000" in capsys.readouterr().out
        assert len(fake_api.requests) == 3

    def test_report_names_the_fingerprint(self, tmp_path, fake_api, capsys):
        self.run("--yes", "--cache-dir", str(tmp_path))
        out = capsys.readouterr().out
        assert "model fingerprint: fp_a" in out
        assert "WARNING" not in out

    def test_report_warns_when_answers_mix_fingerprints(self, tmp_path, fake_api, capsys):
        fake_api.responses = [completion(fingerprint="fp_b")]  # then fp_a for the rest
        self.run("--yes", "--cache-dir", str(tmp_path))
        out = capsys.readouterr().out
        assert "WARNING: answers came from 2 model fingerprints" in out
        assert "   2  fp_a" in out
        assert "   1  fp_b" in out

    def test_claude_model_is_rejected_for_deepseek(self, tmp_path, fake_api):
        with pytest.raises(SystemExit):
            self.run("--model", "sonnet", "--cache-dir", str(tmp_path))
        assert fake_api.requests == []
