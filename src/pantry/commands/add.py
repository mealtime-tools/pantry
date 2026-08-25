"""`pantry add` — acquire one record and store it.

One verb for every way of getting the same thing: a retailer page, a
FoodData Central id, an Open Food Facts barcode, or structured JSON.
The order never changes and the order is the point — resolve the reference,
check what is already held, and only then let a provider spend anything.
"""

import json
from decimal import Decimal
from typing import TextIO

import click
from agentcli import UsageError, json_option

from pantry.commands.describe import describe
from pantry.ids import normalize_id
from pantry.jsonfmt import dumps
from pantry.local import as_result
from pantry.nutrition import nutrients_for_storage
from pantry.output import emit
from pantry.products import (
    NUTRIENT_KEYS,
    PRODUCT_BASES,
    PRODUCT_SOURCES,
    Figure,
    Product,
    is_figure,
    record_keys,
    rescale,
    restate,
)
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
        lines.append("pass --refresh to re-read it, or --input to correct it")
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
        "product": rescale(as_result(product)),
        "changes": changes or [],
        "notes": notes or [],
    }


def _preserved(held: Product | None, product: Product) -> Product:
    """Keep the fields a held record carries and a new reading does not state.

    Rebuilding from the new source alone would drop every field it is silent
    about, the basis included, which no provider can re-supply. Both readings
    are per 100 g, so an old sodium figure stands beside a new energy one.
    There is no way to remove a field: correcting one means restating it.
    """
    if not held:
        return product
    return {**held, **product}


def _changed_fields(before: Product, after: Product) -> list[str]:
    """Stable, human-readable field changes for an explicit refresh."""
    # Both records, so a field only one of them holds is still reported.
    merged = {**before, **after}
    keys = [k for k in record_keys(merged) if k not in ("source", "id")]
    # Serialized rather than `repr`, so a figure reads as the record writes it.
    return [
        f"{key}: {dumps(before.get(key))} -> {dumps(after.get(key))}"
        for key in keys
        if before.get(key) != after.get(key)
    ]


def _read_input(text: str) -> tuple[dict[str, Figure], Decimal | None]:
    """Read a panel and the weight it describes, 100 g if it names none."""
    try:
        # Decimal, so a pasted 0.28 is stored as the 0.28 that was written.
        decoded = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as error:
        raise UsageError(f"input must be JSON: {error}") from None

    if not isinstance(decoded, dict):
        raise UsageError("input must be one JSON object")
    unknown = sorted(set(decoded).difference(NUTRIENT_KEYS, {"grams"}))
    if unknown:
        raise UsageError(f"unknown nutrient keys: {', '.join(unknown)}")

    panel: dict[str, Figure] = {}
    for key in NUTRIENT_KEYS:
        value = decoded.get(key)
        if value is None:
            continue
        if not isinstance(value, (int, Decimal)) or isinstance(value, bool):
            raise UsageError(f"{key} must be a number or null")
        if not is_figure(value) or value < 0:
            raise UsageError(f"{key} must be non-negative and finite")
        panel[key] = Decimal(value)

    grams = decoded.get("grams")
    if grams is not None:
        if not is_figure(grams) or grams <= 0:
            raise UsageError("grams must be a positive finite number")
        grams = Decimal(grams)

    return panel, grams


@click.command("add")
@click.argument("ref", required=False)
@click.option(
    "--input",
    "input_file",
    type=click.File("r", encoding="utf-8"),
    help="Read one JSON object from PATH, or '-' for stdin.",
)
@click.option(
    "--id", "product_id", help="Native id for a manual entry, with no prefix."
)
@click.option("--name", help="The product name as the label prints it.")
@click.option("--brand", default="", help="The brand, if the label names one.")
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
    "--basis",
    type=click.Choice(PRODUCT_BASES),
    help="Input only: what the nutrient figures are measured against. "
    "Absent means as-sold.",
)
@click.option(
    "--basis-note",
    help="Input only: what a consumer must read before scaling, e.g. "
    '"per 100 mL prepared; 1 cube (10.5 g) makes 500 mL".',
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
    input_file: TextIO | None,
    product_id: str | None,
    name: str | None,
    brand: str,
    refresh: bool,
    browser: bool,
    budget: int,
    basis: str | None,
    basis_note: str | None,
    api_key: str | None,
    json_output: bool,
) -> None:
    """Acquire the product REF names and store it in the localstore.

    REF is a retailer url, `usda:<fdcId>` or `off:<barcode>`, and whichever
    provider claims it is the one asked. With --input the record is read from
    a file or stdin and REF may still be a retailer url, which keeps that
    identity: a blocked fetch is a redirection here, not a dead end.
    """
    state = deps(ctx)
    json_output = wants_json(ctx, json_output)
    provider: Provider | None = None

    with guard(json_output, lambda: provider.report() if provider else []):
        # An empty note is still a flag; refusing early spends no page load.
        if (
            basis is not None or basis_note is not None
        ) and input_file is None:
            raise UsageError("--basis and --basis-note need --input")
        if basis_note is not None and basis is None:
            raise UsageError("--basis-note needs --basis")

        reference = resolve_reference(ref) if ref else None

        if input_file is not None:
            product = _manual_record(
                reference,
                input_file.read(),
                product_id=product_id,
                name=name,
                brand=brand,
                basis=basis,
                basis_note=basis_note,
            )
            held = state.store.find(product["source"], product["id"])
            product = _preserved(held, product)
            state.store.add(product)
            _emit(_payload(True, "stored", product), json_output)
            return

        if reference is None:
            raise UsageError(f"add needs {REF_FORMS}, or --input")

        provider = state.providers.get(reference.provider)
        held = state.store.find(reference.source, reference.id)

        # Checked before spending: a held record is not worth a request.
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
        product = _preserved(held, provider.acquire(reference, options))
        changes = _changed_fields(held, product) if held else []

        # A refresh that changed nothing keeps a hand-corrected record.
        if held and not changes:
            _emit(
                _payload(False, "unchanged", held, notes=provider.report()),
                json_output,
            )
            return

        # Persisted the moment it parses: a spent request must not be lost.
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
        # Said every run; under --json it travels inside the one object.
        if not json_output:
            for note in provider.report():
                click.echo(note)
        provider.close()


def _emit(payload: dict, json_output: bool) -> None:
    emit(payload, json_output=json_output, human=_human)


def _manual_record(
    reference: Reference | None,
    text: str,
    *,
    product_id: str | None,
    name: str | None,
    brand: str,
    basis: str | None,
    basis_note: str | None,
) -> Product:
    """Build one record from a JSON panel, whatever failed to load.

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

    figures, grams = _read_input(text)

    # Restated before validation: the ceilings it must clear are per 100 g.
    panel = nutrients_for_storage(restate(figures, grams))

    return build_record(
        source=reference.source if reference else "manual",
        product_id=identifier,
        name=name,
        brand=brand,
        panel=panel,
        url=reference.url if reference else None,
        basis=basis,
        basis_note=basis_note,
    )
