"""Command-line entry point. Groups and wiring; logic is in `commands/`."""

from dataclasses import replace
from pathlib import Path

import click
from agentcli import JsonAwareGroup, skill_group

from pantry import data
from pantry.browser import BrowserTransport, launch_chrome
from pantry.commands.add import add
from pantry.commands.lookup import lookup
from pantry.commands.search import search
from pantry.open_food_facts import OpenFoodFacts, cache_dir
from pantry.providers import Providers
from pantry.providers.local import LocalProvider
from pantry.providers.openfoodfacts import OpenFoodFactsProvider
from pantry.providers.pages import PlainTransport, TransportSet
from pantry.providers.retailer import RetailerProvider
from pantry.providers.usda import UsdaProvider
from pantry.session import Deps
from pantry.store import Store, store_dir, write_atomic


def _open_transports(browser: bool) -> TransportSet:
    """Plain requests by default; a browser only when explicitly asked for.

    Both supermarkets serve their whole nutrition panel to an ordinary
    request, so a browser is a heavier way to get identical bytes. Escalating
    to one the moment a site says no is exactly the behaviour that gets access
    revoked, so it stays opt-in.
    """
    plain = PlainTransport()
    if not browser:
        return TransportSet([plain])

    driver, chrome = launch_chrome()
    page = chrome.new_page()

    def close() -> None:
        chrome.close()
        driver.stop()

    return TransportSet([plain, BrowserTransport(page)], close)


def _providers(store: Store) -> Providers:
    """Every source this run can use.

    Each reads its own credential from the environment, and one without a key
    reports itself disabled rather than failing: a clone with no key still
    searches and looks up.
    """
    return Providers(
        [
            LocalProvider(store),
            OpenFoodFactsProvider(OpenFoodFacts(cache_dir())),
            UsdaProvider(),
            RetailerProvider(_open_transports),
        ]
    )


@click.group(
    cls=JsonAwareGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit exactly one JSON object on stdout. Also accepted after the "
    "subcommand.",
)
@click.pass_context
def main(ctx: click.Context, json_output: bool) -> None:
    """Food product records, their sources, and search over them.

    Every product states the weight its nutrients describe in `grams`: 100
    unless `--grams` names another. No pack or serving size is held. Identity
    is (source, id).
    """
    # Tests inject prepared dependencies; only build the real ones otherwise.
    # Replaced rather than mutated so one injected set can serve several runs.
    if isinstance(ctx.obj, Deps):
        ctx.obj = replace(
            ctx.obj, json_output=ctx.obj.json_output or json_output
        )
        return

    store = Store(lambda: data.read_shards(data.data_dir()), store_dir())
    ctx.obj = Deps(
        store=store,
        providers=_providers(store),
        write_out=lambda path, text: write_atomic(Path(path), text),
        json_output=json_output,
    )


for command in (
    search,
    lookup,
    add,
    skill_group(name="pantry", package="pantry"),
):
    main.add_command(command)
