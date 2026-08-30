"""`pantry search` — one query, every provider that is willing to answer."""

from decimal import Decimal

import click
from agentcli import json_option, limit_option

from pantry.commands import grams_option
from pantry.commands.describe import describe
from pantry.local import result_with_nulls
from pantry.output import emit
from pantry.products import rescale
from pantry.providers import SHOP_NAMES
from pantry.session import deps, guard, wants_json

# What a result may be ordered by, and which way round is "best first".
# `protein-per-kcal` wants the most of what every panel already states.
SORTS = ("protein-per-kcal",)

# A filter or a sort needs candidates to work on. Asking a provider for
# exactly `--limit` and then discarding most of them would answer almost
# nothing, and would sort the best name matches rather than the best products.
# So a filtered search asks for a multiple and truncates once it is done.
CANDIDATE_POOL = 20


def _human(payload: dict) -> list[str]:
    if not payload["results"]:
        return [f'no products match "{payload["query"]}"']
    return [describe(result) for result in payload["results"]]


def _density(result: dict) -> Decimal | None:
    """Grams of protein per 100 kcal, where both figures are known.

    Zero energy is not a division: a product with no calories has no protein
    density, which is unknown rather than infinite.
    """
    kcal, protein = result.get("kcal"), result.get("protein")
    if kcal is None or protein is None or kcal <= 0:
        return None

    return Decimal(protein) / Decimal(kcal) * 100


def _sorted(results: list[dict], sort_by: str) -> list[dict]:
    """Best first, with everything the key cannot judge left at the end.

    A result missing the figure is not ranked as a zero — that would put the
    products nothing is known about at one end of the list as if that were an
    answer. They keep their existing order, after the ones that can be ranked.
    """
    keys = [(_density(r), r) for r in results]
    ranked = [(k, r) for k, r in keys if k is not None]
    ranked.sort(key=lambda pair: -pair[0])

    unranked = [r for k, r in keys if k is None]
    return [r for _, r in ranked] + unranked


@click.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option(
    "--shop",
    type=click.Choice(SHOP_NAMES),
    help="Search this live shop instead of the local store.",
)
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(SORTS),
    help="Reorder results. Anything the key needs and lacks sorts last.",
)
@grams_option
@json_option
@limit_option()
@click.pass_context
def search(
    ctx: click.Context,
    query: tuple[str, ...],
    shop: str | None,
    sort_by: str | None,
    grams: Decimal | None,
    json_output: bool,
    limit: int,
) -> None:
    """Search for QUERY, locally by default.

    A network call is opted into with `--shop`; without it only the store is
    searched. Finding nothing is success, an empty list and exit 0. `--grams`
    applies to every result alike, so a response never mixes bases.

    With `--sort`, `--limit` counts what survives instead: the providers are
    asked for a wider pool first, so the sort ranks products rather than name
    matches.
    """
    json_output = wants_json(ctx, json_output)

    with guard(json_output):
        text = " ".join(query)
        providers = deps(ctx).providers.searchers(shop=shop)

        narrowing = sort_by is not None
        asked = limit * CANDIDATE_POOL if narrowing else limit

        results: list[dict] = []
        for provider in providers:
            results.extend(
                rescale(result_with_nulls(result), grams)
                for result in provider.search(text, asked)
            )

        if sort_by:
            results = _sorted(results, sort_by)
        if narrowing:
            results = results[:limit]

        emit(
            {
                "query": text,
                "sources": [provider.name for provider in providers],
                "results": results,
            },
            json_output=json_output,
            human=_human,
        )
