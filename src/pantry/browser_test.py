"""What pantry tells someone who has no browser installed."""

import importlib.metadata

from pantry.browser import BROWSER_HINT


def test_the_hint_names_the_distribution_that_carries_the_extra() -> None:
    """This message is the only install guidance pantry prints.

    It said `uv pip install 'pantry[browser]'`, wrong twice: the distribution
    is `mealtime-pantry`, and `uv pip install` does not reach the environment
    `uv tool install` builds, so following it verbatim either fails to resolve
    or silently changes nothing. Reading the name back from the metadata means
    a rename breaks this test rather than the advice.
    """
    distribution = importlib.metadata.metadata("mealtime-pantry")["Name"]

    assert f"{distribution}[browser]" in BROWSER_HINT
    assert "uv tool install" in BROWSER_HINT
