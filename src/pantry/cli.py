"""Command-line entry point. Groups and wiring; logic is in `commands/`."""

import sys
from dataclasses import replace
from pathlib import Path

import click
from agentcli import JsonAwareGroup, guide_command, skill_group

from pantry import data, helptext
from pantry.browser import BrowserTransport, launch_chrome
from pantry.commands.add import add
from pantry.commands.annotate import annotate
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


def _read_stdin(optional: bool = False) -> str:
    """Read the nutrition panel a user pastes.

    A terminal is told how to finish, because a command that appears to hang
    on stdin is indistinguishable from one that has crashed.
    """
    if sys.stdin.isatty():
        if optional:
            return ""
        click.echo("paste the nutrition panel, then press Ctrl-D:", err=True)

    return sys.stdin.read()


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

    Nutrients are per 100 g in every record. Identity is the pair
    (source, id). Run `pantry guide` for the full agent-facing manual.
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
        read_stdin=_read_stdin,
        json_output=json_output,
    )


for command in (
    search,
    lookup,
    add,
    annotate,
    guide_command(helptext.GUIDE),
    skill_group(name="pantry", package="pantry"),
):
    main.add_command(command)
