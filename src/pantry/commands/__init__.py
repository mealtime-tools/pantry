"""One module per subcommand, plus the flags more than one of them takes."""

from decimal import Decimal, InvalidOperation
from typing import Any

import click


class GramsType(click.ParamType):
    """A weight: positive and finite, which `FloatRange` cannot express.

    A Decimal, because the figures it restates are decimals: a weight read as
    a float would put binary noise back into every one of them.
    """

    name = "grams"

    def convert(
        self,
        value: Any,
        param: click.Parameter | None = None,
        ctx: click.Context | None = None,
    ) -> Decimal:
        try:
            weight = Decimal(str(value))
        except (TypeError, InvalidOperation):
            self.fail(f"{value!r} is not a number of grams", param, ctx)

        if not weight.is_finite() or weight <= 0:
            self.fail(
                f"{value!r} is not a weight: grams must be positive and "
                "finite",
                param,
                ctx,
            )
        return weight


# Shared: scaling one result and a list of them is the same request.
grams_option = click.option(
    "--grams",
    type=GramsType(),
    help="State the nutrients for this many grams, and report that weight as "
    "the basis. Without it they describe 100 g.",
)
