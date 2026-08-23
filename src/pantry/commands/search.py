"""`pantry search` — one query, every provider that is willing to answer."""

import click
from agentcli import emit, json_option, limit_option

from pantry.commands import grams_option
from pantry.commands.describe import describe
from pantry.local import result_with_nulls
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

    A network call has a cost the caller should opt into, so remote providers
    answer only under --remote. Finding nothing is success: the payload
    carries an empty list and the exit code stays 0, because "this product is
    not held" is the answer that makes it safe to check before spending a page
    load. `--limit` applies per provider, every result carries the `source` it
    came from, and `sources` names the providers that answered — one with no
    credential is skipped without a message.

    `--grams` applies to every result alike: one list must not mix bases.
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
