"""Rules 2, 3, 4 and 5: what a page load costs and when it is refused."""

import json

import pytest
from pantry.conftest import (
    COLES_URL,
    FakeTransport,
    TransportRecorder,
    coles_page,
)

from pantry.providers.pages import (
    Blocked,
    BudgetExhausted,
    PageBudget,
    PageLoader,
)

HELD = {
    "source": "coles",
    "id": "1047",
    "name": "Example Bread",
    "brand": "Example",
    "kcal": 234.2,
    "protein": 8.5,
    "fat": 3.6,
    "carbohydrates": 38.4,
}


def test_a_held_product_is_never_fetched(make_deps, run) -> None:
    recorder = TransportRecorder(FakeTransport("plain", []))
    deps = make_deps([HELD], open_transports=recorder)

    result = run(deps, "add", COLES_URL)

    assert result.exit_code == 0
    assert "already held" in result.output
    # No transport was even opened, let alone a request made.
    assert recorder.opened == []
    assert recorder.transport.calls == []


def test_budget_is_claimed_before_the_request_and_counted_when_refused():
    transport = FakeTransport("plain", [(403, "")])
    loader = PageLoader([transport], PageBudget(2), pace_ms=0)

    # A 403 is a refusal, and the site served it: the load is spent.
    with pytest.raises(Blocked):
        loader.load(COLES_URL)
    assert loader.spent == 1

    # An exhausted budget refuses before anything reaches the network.
    empty = PageLoader([transport], PageBudget(0), pace_ms=0)
    with pytest.raises(BudgetExhausted):
        empty.load(COLES_URL)
    assert transport.calls == [COLES_URL]


def test_a_block_ends_the_session_with_no_retry() -> None:
    transport = FakeTransport("plain", [(200, "Pardon Our Interruption")])
    loader = PageLoader([transport], PageBudget(4), pace_ms=0)

    with pytest.raises(Blocked):
        loader.load(COLES_URL)

    # Every later load is refused without spending anything and without a
    # second request: no retry, no second user agent, no escalation.
    with pytest.raises(Blocked):
        loader.load("https://www.coles.com.au/product/other-2/")
    assert len(transport.calls) == 1
    assert loader.spent == 1


def test_add_reports_the_spend_and_never_opens_a_browser_on_a_block(
    make_deps, run, store_path
):
    recorder = TransportRecorder(FakeTransport("plain", [(429, "")]))
    deps = make_deps([], open_transports=recorder)

    result = run(deps, "add", COLES_URL)

    assert result.exit_code == 2
    assert "used 1 of 4 page loads this run" in result.output
    # The browser is opt-in; a block is never what turns it on.
    assert recorder.opened == [False]
    assert not (store_path / "coles.jsonl").exists()


def test_the_spend_survives_inside_the_single_json_object(make_deps, run):
    """Rule 10 and rule 3 at once: one object, and it still says the cost."""
    recorder = TransportRecorder(FakeTransport("plain", [(429, "")]))
    deps = make_deps([], open_transports=recorder)

    result = run(deps, "--json", "add", COLES_URL, "--budget", "2")

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "used 1 of 2 page loads this run" in payload["error"]["message"]


def test_a_malformed_panel_is_refused_and_nothing_is_stored(
    make_deps, run, store_path
):
    page = coles_page(panel=[{"nutrient": "Protein", "value": "8.5g"}])
    recorder = TransportRecorder(FakeTransport("plain", [(200, page)]))
    deps = make_deps([], open_transports=recorder)

    result = run(deps, "add", COLES_URL)

    assert result.exit_code == 1
    assert "no usable energy" in result.output
    # The page load is still reported, and no zero-calorie record was written.
    assert "used 1 of 4 page loads this run" in result.output
    assert not (store_path / "coles.jsonl").exists()


def test_a_good_page_is_stored_immediately(make_deps, run, store_path) -> None:
    recorder = TransportRecorder(FakeTransport("plain", [(200, coles_page())]))
    deps = make_deps([], open_transports=recorder)

    result = run(deps, "add", COLES_URL)

    assert result.exit_code == 0
    stored = (store_path / "coles.jsonl").read_text(encoding="utf-8")
    # The filename records the source, so the row does not repeat it.
    assert stored.startswith('{"id":"1047"')
    assert '"source"' not in stored
    assert '"kj":980' in stored and '"kcal":234.2' in stored
    # The panel's 400 mg sodium row survives the page as the grams a record
    # holds, sorted in beside the other vocabulary nutrients.
    # Saturated fat comes across too, now that a structured row is resolved
    # against the shared vocabulary instead of a local list of three names.
    assert (
        '"dietary_fiber":4.1,"saturated_fat":0.6,"sodium":0.4,"sugar":2.2'
    ) in stored


def test_a_refresh_reports_its_changes_and_needs_the_record_held(
    make_deps, run, store_path
):
    page = coles_page(name="Example Bread Renamed")
    recorder = TransportRecorder(
        FakeTransport("plain", [(200, page), (200, page)])
    )
    deps = make_deps([HELD], open_transports=recorder)

    # There is no age-based refresh, and nothing to refresh is a refusal
    # rather than a first fetch in disguise.
    absent = "https://www.coles.com.au/product/example-2/"
    missing = run(deps, "add", absent, "--refresh")
    assert missing.exit_code == 1
    assert "is not held" in missing.output

    refreshed = run(deps, "add", COLES_URL, "--refresh")

    assert refreshed.exit_code == 0
    assert "refresh changes for coles:1047" in refreshed.output
    assert "Example Bread Renamed" in (store_path / "coles.jsonl").read_text(
        encoding="utf-8"
    )

    # A refresh that changed nothing leaves the record alone, so a correction
    # made by hand is not rewritten by an identical page.
    again = run(deps, "add", COLES_URL, "--refresh")
    assert again.exit_code == 0
    assert "no field changes for coles:1047" in again.output
