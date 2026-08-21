"""`pantry add` — acquire one record and store it.

One verb for every way of getting the same thing: a retailer page, a
FoodData Central id, an Open Food Facts barcode, or a panel pasted by hand.
The order never changes and the order is the point — resolve the reference,
check what is already held, and only then let a provider spend anything.
"""

import click
from agentcli import UsageError, emit, json_option

from pantry.commands.describe import describe
from pantry.ids import normalize_id
from pantry.nutrition import nutrients_for_storage, parse_amount, parse_panel
from pantry.products import PRODUCT_KEYS, PRODUCT_SOURCES, Product
from pantry.providers import (
    REF_FORMS,
    AcquireOptions,
    Provider,
    Reference,
    resolve_reference,
)
from pantry.providers.retailer import DEFAULT_PAGE_BUDGET
from pantry.session import Deps, deps, guard, wants_json
from pantry.sites import build_record


def _human(payload: dict) -> list[str]:
    """Notes are deliberately absent: the caller echoes them either way."""
    lines = []
    label = f"{payload['source']}:{payload['id']}"

    if payload["changes"]:
        lines.append(f"refresh changes for {label}:")
        lines.extend(f"  {change}" for change in payload["changes"])

    if payload["stored"]:
        lines.append(f"stored {describe(payload['product'])}")
    elif payload["reason"] == "held":
        lines.append(f"already held: {describe(payload['product'])}")
        lines.append("pass --refresh to re-read it, or --manual to correct it")
    else:
        lines.append(f"no field changes for {label}")

    return lines


def _payload(
    stored: bool,
    reason: str,
    product: Product,
    *,
    changes: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict:
    """The one shape every way of adding a record answers in."""
    return {
        "stored": stored,
        "reason": reason,
        "source": product["source"],
        "id": product["id"],
        "product": product,
        "changes": changes or [],
        "notes": notes or [],
    }


def _changed_fields(before: Product, after: Product) -> list[str]:
    """Stable, human-readable field changes for an explicit refresh."""
    keys = [k for k in PRODUCT_KEYS if k not in ("source", "id")]
    return [
        f"{key}: {before.get(key)!r} -> {after.get(key)!r}"
        for key in keys
        if before.get(key) != after.get(key)
    ]


@click.command("add")
@click.argument("ref", required=False)
@click.option(
    "--manual",
    is_flag=True,
    help="Read the panel from stdin instead. Never touches the network.",
)
@click.option(
    "--id", "product_id", help="Native id for a manual entry, with no prefix."
)
@click.option("--name", help="The product name as the label prints it.")
@click.option("--brand", default="", help="The brand, if the label names one.")
@click.option("--serving", help='Serving size as written, e.g. "59g".')
@click.option("--total", help='Pack size as written, e.g. "450g".')
@click.option(
    "--refresh",
    is_flag=True,
    help="Re-read a record already held. There is no age-based refresh.",
)
@click.option(
    "--browser",
    is_flag=True,
    help="Retailer only: fall back to local Chrome if a plain request is "
    "refused. Explicit on purpose; a block never escalates on its own.",
)
@click.option(
    "--budget",
    type=click.IntRange(min=0),
    default=DEFAULT_PAGE_BUDGET,
    show_default=True,
    help="Retailer only: page loads this run may spend, counted even when "
    "refused.",
)
@click.option(
    "--zero-calorie",
    is_flag=True,
    help="Confirm an absent or all-zero panel. Refused if anything is set.",
)
@click.option(
    "--api-key",
    help="USDA only. Defaults to $USDA_API_KEY or .env; never printed.",
)
@json_option
@click.pass_context
def add(
    ctx: click.Context,
    ref: str | None,
    manual: bool,
    product_id: str | None,
    name: str | None,
    brand: str,
    serving: str | None,
    total: str | None,
    refresh: bool,
    browser: bool,
    budget: int,
    zero_calorie: bool,
    api_key: str | None,
    json_output: bool,
) -> None:
    """Acquire the product REF names and store it in the localstore.

    REF is a retailer url, `usda:<fdcId>` or `off:<barcode>`, and whichever
    provider claims it is the one asked. With --manual the panel is read from
    stdin instead and REF may still be a retailer url, which keeps that
    identity: a blocked fetch is a redirection here, not a dead end.
    """
    state = deps(ctx)
    json_output = wants_json(ctx, json_output)
    provider: Provider | None = None

    with guard(json_output, lambda: provider.report() if provider else []):
        reference = resolve_reference(ref) if ref else None

        if manual:
            product = _manual_record(
                state,
                reference,
                product_id=product_id,
                name=name,
                brand=brand,
                serving=serving,
                total=total,
                zero_calorie=zero_calorie,
            )
            state.store.add(product)
            _emit(_payload(True, "stored", product), json_output)
            return

        if reference is None:
            raise UsageError(f"add needs {REF_FORMS}, or --manual")

        provider = state.providers.get(reference.provider)
        held = state.store.find(reference.source, reference.id)

        # Checked before anything is spent: a record already on disk is not
        # worth a request the user cannot get back.
        if held and not refresh:
            _emit(_payload(False, "held", held), json_output)
            return
        if refresh and not held:
            raise UsageError(
                f"{reference.source}:{reference.id} is not held; "
                f"add it without --refresh first"
            )

        _acquire(
            state,
            provider,
            reference,
            AcquireOptions(
                zero_calorie=zero_calorie,
                browser=browser,
                budget=budget,
                api_key=api_key,
            ),
            held,
            json_output,
        )


def _acquire(
    state: Deps,
    provider: Provider,
    reference: Reference,
    options: AcquireOptions,
    held: Product | None,
    json_output: bool,
) -> None:
    """Spend the request, then persist the moment the answer parses."""
    try:
        product = provider.acquire(reference, options)
        changes = _changed_fields(held, product) if held else []

        # A refresh that changed nothing leaves the localstore alone,
        # so a record
        # keeps whatever the user corrected by hand.
        if held and not changes:
            _emit(
                _payload(False, "unchanged", held, notes=provider.report()),
                json_output,
            )
            return

        # Persisted the moment it parses: a request already spent must never
        # be lost to a later failure in the same run.
        state.store.add(product)
        _emit(
            _payload(
                True,
                "stored",
                product,
                changes=changes,
                notes=provider.report(),
            ),
            json_output,
        )
    finally:
        # Said every run, successful or not. Under --json it travels inside
        # the one object instead, so it is not echoed twice.
        if not json_output:
            for note in provider.report():
                click.echo(note)
        provider.close()


def _emit(payload: dict, json_output: bool) -> None:
    emit(payload, json_output=json_output, human=_human)


def _manual_record(
    state: Deps,
    reference: Reference | None,
    *,
    product_id: str | None,
    name: str | None,
    brand: str,
    serving: str | None,
    total: str | None,
    zero_calorie: bool,
) -> Product:
    """Build one record from a pasted panel, no matter what refused to load.

    A url supplies the native id, the source and the link at once; an explicit
    --id is always a manual identity.
    """
    if reference and reference.provider != "retailer":
        raise UsageError(
            "a manual entry cannot claim a usda or openfoodfacts identity"
        )

    identifier = normalize_id(
        product_id or (reference.id if reference else "")
    )
    if not identifier:
        raise UsageError("a manual entry needs --id or a retailer url")
    if any(identifier.startswith(f"{s}:") for s in PRODUCT_SOURCES):
        raise UsageError(
            "--id is the native id only; source prefixes are not accepted"
        )
    if not name:
        raise UsageError("a manual entry needs --name")

    panel = nutrients_for_storage(
        parse_panel(state.read_stdin(optional=zero_calorie)), zero_calorie
    )

    return build_record(
        source=reference.source if reference else "manual",
        product_id=identifier,
        name=name,
        brand=brand,
        panel=panel,
        url=reference.url if reference else None,
        serving=parse_amount(serving),
        total=parse_amount(total),
    )
