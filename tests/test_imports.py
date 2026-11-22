import os
import subprocess
import sys
from pathlib import Path

import item_appraiser

SRC = str(Path(item_appraiser.__file__).parent.parent)


def run(code: str) -> str:
    env = {**os.environ, "PYTHONPATH": SRC}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env
    )
    return result.stdout.strip()


def test_core_import_does_not_load_provider_sdks():
    out = run(
        "import sys\n"
        "import item_appraiser\n"
        "from item_appraiser import Appraisal, buy_value, loan_kg_co2e\n"
        "from item_appraiser import climate, policy\n"
        "print(sorted(m for m in ('anthropic', 'openai') if m in sys.modules))\n"
    )
    assert out == "[]"


def test_appraisers_load_on_first_use():
    out = run(
        "import sys\n"
        "from item_appraiser import ClaudeAppraiser, DeepSeekAppraiser\n"
        "print(ClaudeAppraiser.__module__, DeepSeekAppraiser.__module__)\n"
        "print(sorted(m for m in ('anthropic', 'openai') if m in sys.modules))\n"
    )
    assert out.splitlines() == [
        "item_appraiser.claude item_appraiser.deepseek",
        "['anthropic', 'openai']",
    ]


def test_unknown_attribute_still_raises():
    try:
        item_appraiser.NotAThing  # noqa: B018
    except AttributeError as error:
        assert "NotAThing" in str(error)
    else:
        raise AssertionError("expected AttributeError")


def test_dir_lists_lazy_appraisers():
    assert {"ClaudeAppraiser", "DeepSeekAppraiser"} <= set(dir(item_appraiser))
