import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_claude import OUTPUT, FakeClient, message

import item_appraiser
from item_appraiser import cli
from item_appraiser.claude import ClaudeAppraiser
from item_appraiser.models import AppraisalError

SRC = str(Path(item_appraiser.__file__).parent.parent)
CLIMATE_OUTPUT = {**OUTPUT, "footprint_category": "plastic household goods"}


@pytest.fixture
def fake_claude(monkeypatch, tmp_path):
    """Route the CLI to a real ClaudeAppraiser talking to a fake client."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    client = FakeClient(message(CLIMATE_OUTPUT))

    def build(provider, impacts, cache_dir):
        assert provider == "claude"
        return ClaudeAppraiser(impacts=impacts, client=client, image_check=lambda url: True)

    monkeypatch.setattr(cli, "build_appraiser", build)
    return client


def test_choose_provider_uses_the_only_key_set():
    assert cli.choose_provider(None, {"DEEPSEEK_API_KEY": "k"}) == "deepseek"
    assert cli.choose_provider(None, {"ANTHROPIC_API_KEY": "k"}) == "claude"


def test_choose_provider_needs_a_choice_with_both_or_no_keys():
    both = {"ANTHROPIC_API_KEY": "k", "DEEPSEEK_API_KEY": "k"}
    assert cli.choose_provider("deepseek", both) == "deepseek"
    with pytest.raises(cli.UsageError, match="--provider"):
        cli.choose_provider(None, both)
    with pytest.raises(cli.UsageError, match="ANTHROPIC_API_KEY"):
        cli.choose_provider(None, {})
    with pytest.raises(cli.UsageError, match="DEEPSEEK_API_KEY"):
        cli.choose_provider("deepseek", {"ANTHROPIC_API_KEY": "k"})


def test_prints_money_and_climate(fake_claude, capsys):
    cli.main(["Garden gnome", "-d", "Slightly chipped", "--photo", "https://example.com/g.jpg"])
    out = capsys.readouterr().out
    assert "Assumption: Priced as a mid-size resin gnome." in out
    assert "$37.50" in out  # 3 x $12.50
    assert "3 x $12.50" in out
    assert "Buy value" in out and "$22.50" in out  # used: 0.6
    assert "Loan value" in out and "$11.25" in out
    assert "as plastic household goods" in out
    assert "Giving it away" in out and "Lending it once" in out
    [request] = fake_claude.requests
    assert "Garden gnome" in json.dumps(request["messages"])
    assert "https://example.com/g.jpg" in json.dumps(request["messages"])


def test_money_only_leaves_out_climate(fake_claude, capsys):
    fake_claude.responses = [message(OUTPUT)]
    cli.main(["Garden gnome", "--money-only"])
    out = capsys.readouterr().out
    assert "Buy value" in out
    assert "kg" not in out


def test_json_output_is_to_dict(fake_claude, capsys):
    cli.main(["Garden gnome", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["new_price_usd"] == 37.5
    assert data["buy_value_usd"] == 22.5
    assert data["footprint_category"] == "plastic household goods"
    assert data["giveaway_kg_co2e"] is not None


def test_no_key_exits_with_a_hint(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    with pytest.raises(SystemExit) as exit:
        cli.main(["Toilet plunger"])
    assert exit.value.code == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_unusable_answer_exits_cleanly(fake_claude, monkeypatch, capsys):
    def fail(listing):
        raise AppraisalError("blank answer")

    monkeypatch.setattr(ClaudeAppraiser, "appraise", lambda self, listing: fail(listing))
    with pytest.raises(SystemExit) as exit:
        cli.main(["Toilet plunger"])
    assert exit.value.code == 1
    assert "try again" in capsys.readouterr().err


@pytest.mark.parametrize("provider, sdk", [("claude", "anthropic"), ("deepseek", "openai")])
def test_missing_extra_names_the_install_command(provider, sdk):
    # Block the SDK import, as if the extra weren't installed.
    code = (
        f"import sys; sys.modules[{sdk!r}] = None\n"
        "from item_appraiser import cli\n"
        f"cli.main([{'--provider'!r}, {provider!r}, 'plunger'])\n"
    )
    env = {**os.environ, "PYTHONPATH": SRC, "ANTHROPIC_API_KEY": "k", "DEEPSEEK_API_KEY": "k"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert result.returncode == 2
    assert f"pip install 'item-appraiser[{provider}]'" in result.stderr


def test_importing_the_cli_does_not_load_provider_sdks():
    code = (
        "import sys\n"
        "from item_appraiser import cli\n"
        "print(sorted(m for m in ('anthropic', 'openai') if m in sys.modules))\n"
    )
    env = {**os.environ, "PYTHONPATH": SRC}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert result.stdout.strip() == "[]"
