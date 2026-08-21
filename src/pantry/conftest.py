"""Shared fakes. No test touches the network, a browser, or a real home."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pantry.cli import main
from pantry.data import data_dir
from pantry.open_food_facts import OpenFoodFacts
from pantry.providers import Providers
from pantry.providers.local import LocalProvider
from pantry.providers.openfoodfacts import OpenFoodFactsProvider
from pantry.providers.pages import TransportSet
from pantry.providers.retailer import RetailerProvider
from pantry.providers.usda import UsdaProvider
from pantry.session import Deps
from pantry.store import Store

# A minimal but realistic Coles panel: two breakdowns, only one per 100 g.
COLES_PANEL = [
    {"nutrient": "Energy", "value": "980kJ"},
    {"nutrient": "Protein", "value": "8.5g"},
    {"nutrient": "Fat, Total", "value": "3.6g"},
    {"nutrient": "- Saturated", "value": "0.6g"},
    {"nutrient": "Carbohydrate", "value": "38.4g"},
    {"nutrient": "- Sugars", "value": "2.2g"},
    {"nutrient": "Dietary Fibre", "value": "4.1g"},
    {"nutrient": "Sodium", "value": "400mg"},
]

COLES_URL = "https://www.coles.com.au/product/example-bread-450g-1047"


def coles_page(panel: list[dict] | None = None, name: str = "Example Bread"):
    """A page in the shape the site really serves: server-rendered payload."""
    payload = {
        "props": {
            "pageProps": {
                "product": {
                    "name": name,
                    "brand": "Example",
                    "size": "450g",
                    "nutrition": {
                        "servingSize": "47g",
                        "breakdown": [
                            {
                                "title": "Per Serving",
                                "nutrients": [
                                    {"nutrient": "Energy", "value": "460kJ"}
                                ],
                            },
                            {
                                "title": "Per 100g",
                                "nutrients": (
                                    COLES_PANEL if panel is None else panel
                                ),
                            },
                        ],
                    },
                }
            }
        }
    }
    body = json.dumps(payload)
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        f"{body}</script></html>"
    )


class FakeTransport:
    """Records every call, so a test can assert nothing was requested."""

    def __init__(self, name: str, responses: list[tuple[int, str]]) -> None:
        self.name = name
        self._responses = list(responses)
        self.calls: list[str] = []

    def load(self, url: str) -> tuple[int, str]:
        self.calls.append(url)
        if not self._responses:
            raise AssertionError(f"{self.name} was called more than expected")
        return self._responses.pop(0)


class TransportRecorder:
    """Stands in for opening transports, and remembers whether it was asked."""

    def __init__(self, transport: FakeTransport | None = None) -> None:
        self.transport = transport
        self.opened: list[bool] = []
        self.closed = 0

    def __call__(self, browser: bool) -> TransportSet:
        self.opened.append(browser)
        transports = [self.transport] if self.transport else []

        def close() -> None:
            self.closed += 1

        return TransportSet(transports, close)


def no_network(*args, **kwargs):
    """The default for every injected client: reaching out is a test failure."""
    raise AssertionError("a test tried to use the network")


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """The user's records, always under tmp_path and never in a checkout.

    A directory of `<source>.jsonl` shards, the same layout the frozen data
    ships in.
    """
    return tmp_path / "config" / "pantry"


@pytest.fixture
def make_deps(tmp_path: Path, store_path: Path):
    """Build a fully injected dependency set for one CLI run."""

    def build(base: list[dict] | None = None, **kwargs) -> Deps:
        recorder = kwargs.pop("open_transports", None) or TransportRecorder()
        off_get = kwargs.pop("off_get", None) or no_network
        usda_opener = kwargs.pop("usda_opener", None) or no_network
        env = kwargs.pop("env", {})

        store = Store(lambda: list(base or []), store_path)
        providers = Providers(
            [
                LocalProvider(store),
                OpenFoodFactsProvider(
                    OpenFoodFacts(tmp_path / "cache", get=off_get)
                ),
                UsdaProvider(opener=usda_opener, env=env),
                # No real pause, so the suite stays fast.
                RetailerProvider(
                    recorder, pace_ms=0, sleep=lambda seconds: None
                ),
            ]
        )

        return Deps(
            store=store,
            providers=providers,
            write_out=lambda path, text: (
                Path(path).parent.mkdir(parents=True, exist_ok=True),
                Path(path).write_text(text, encoding="utf-8"),
            )[0],
            read_stdin=lambda optional=False: "",
            **kwargs,
        )

    return build


@pytest.fixture
def run():
    """Invoke the CLI with injected dependencies and no isolated filesystem."""

    def invoke(deps: Deps, *args: str, stdin: str | None = None):
        if stdin is not None:
            deps.read_stdin = lambda optional=False: stdin
        return CliRunner().invoke(main, list(args), obj=deps)

    return invoke


def has_shard(source: str) -> bool:
    """Whether a frozen shard is present in this checkout.

    `coles.jsonl` is a local-only scrape: it is not redistributed, so a
    public checkout has AFCD and nothing else. Tests that assert against it
    skip rather than fail, because its absence is a fact about the checkout
    and not a defect.
    """
    return (data_dir() / f"{source}.jsonl").is_file()


requires_coles = pytest.mark.skipif(
    not has_shard("coles"),
    reason="the Coles shard is local-only and not distributed",
)
