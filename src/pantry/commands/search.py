"""`pantry search` — one query, every provider that is willing to answer."""

import click
from agentcli import json_option, limit_option

from pantry.commands import grams_option
from pantry.commands.describe import describe
from pantry.local import result_with_nulls
from pantry.output import emit
from pantry.products import rescale
from pantry.providers import PROVIDER_NAMES
from pantry.session import deps, guard, wants_json


def _human(payload: dict) -> list[str]:
    if not payload["results"]:
        return [f'no products match "{payload["query"]}"']
    return [describe(result) for result in payload["results"]]


@click.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option(
    "--source",
    "sources",
    multiple=True,
    type=click.Choice(PROVIDER_NAMES),
    help="Ask only this provider. Repeatable.",
)
@click.option(
    "--remote",
    is_flag=True,
    help="Also ask the providers that cost a network request.",
)
@grams_option
@json_option
@limit_option()
@click.pass_context
def search(
    ctx: click.Context,
    query: tuple[str, ...],
    sources: tuple[str, ...],
    remote: bool,
    grams: float | None,
    json_output: bool,
    limit: int,
) -> None:
    """Search for QUERY, locally by default.

    A network call is opted into: remote providers answer only under --remote.
    Finding nothing is success, an empty list and exit 0, so a check before
    spending a page load is safe. `--limit` is per provider, `sources` names
    who answered, and `--grams` applies to every result alike: no mixed bases.
    """
    json_output = wants_json(ctx, json_output)

    with guard(json_output):
        text = " ".join(query)
        providers = deps(ctx).providers.searchers(
            remote=remote, only=tuple(sources)
        )

        results: list[dict] = []
        for provider in providers:
            results.extend(
                rescale(result_with_nulls(result), grams)
                for result in provider.search(text, limit)
            )

        emit(
            {
                "query": text,
                "sources": [provider.name for provider in providers],
                "results": results,
            },
            json_output=json_output,
            human=_human,
        )
