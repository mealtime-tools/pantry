"""Everything the commands need, injected, plus one place to report failures.

Nothing in `commands/` constructs a store, a network client or a browser. That
is what lets the whole command surface be tested with no network, no browser
and no home directory.
"""

import contextlib
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path

import click
from agentcli import emit_error

from pantry.nutrition import NutritionError
from pantry.open_food_facts import RemoteFailure
from pantry.products import ProductError
from pantry.providers import Providers
from pantry.providers.pages import Blocked, BudgetExhausted
from pantry.sites import SiteError
from pantry.store import Store

# A refusal the user must resolve exits 1, a remote one 2. Never retried.
_EXIT_CODES: tuple[tuple[type[Exception], int], ...] = (
    (Blocked, 2),
    (RemoteFailure, 2),
    (BudgetExhausted, 1),
    (ProductError, 1),
    (NutritionError, 1),
    (SiteError, 1),
    (OSError, 1),
)


@dataclass
class Deps:
    """The effects the CLI has."""

    store: Store
    providers: Providers
    write_out: Callable[[Path, str], None]
    json_output: bool = False


def deps(ctx: click.Context) -> Deps:
    """The injected effects for this run."""
    return ctx.ensure_object(Deps)


def wants_json(ctx: click.Context, json_output: bool) -> bool:
    """`--json` is accepted before or after the subcommand; either wins."""
    return json_output or deps(ctx).json_output


@contextlib.contextmanager
def guard(
    json_output: bool, notes: Callable[[], list[str]] | None = None
) -> Generator[None]:
    """Turn a refusal into the documented exit code and one JSON object.

    Requesting `--json` is a promise that stdout is parseable, so an error
    goes there too rather than to stderr. `notes` carries what a provider
    already spent: under `--json` there is only one object to say it in, so it
    is folded into the message rather than lost.
    """
    try:
        yield
    except click.ClickException as error:
        # Click would route this to stderr, where a JSON caller never looks.
        emit_error(
            _message(error.format_message(), json_output, notes),
            json_output=json_output,
        )
        raise SystemExit(error.exit_code) from error
    except Exception as error:
        code = next(
            (c for kind, c in _EXIT_CODES if isinstance(error, kind)), None
        )
        if code is None:
            raise
        emit_error(
            _message(str(error), json_output, notes), json_output=json_output
        )
        raise SystemExit(code) from error


def _message(
    reason: str, json_output: bool, notes: Callable[[], list[str]] | None
) -> str:
    """The failure, plus what it cost when only one object may be emitted."""
    spent = notes() if json_output and notes else []
    return "; ".join([reason, *spent])
