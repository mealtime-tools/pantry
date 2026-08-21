"""Resolving the FoodData Central key.

Order: `--api-key`, `$USDA_API_KEY`, then `.env`. The real environment comes
first so an exported variable always beats a stale file.

The key is never logged, echoed, or put in an error message. Only the fact
that one was found, and where from, is ever printed.

Almost nothing needs this. A USDA food is imported once and its macros are
frozen into the record, so search, lookup and every recipe afterwards work with
no credential at all.
"""

import os
from collections.abc import Mapping

from agentcli import UsageError
from dotenv import load_dotenv

ENV_VAR = "USDA_API_KEY"

SIGNUP_URL = "https://fdc.nal.usda.gov/api-key-signup.html"

_GUIDANCE = (
    f"no USDA key found. One is free from {SIGNUP_URL}. Set ${ENV_VAR}, put it "
    f"in .env, or pass --api-key. Only importing a USDA food needs it."
)


def find_key(
    explicit: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """The first key available, or nothing. Never refuses.

    Having no key is how a provider reports itself unconfigured, which is not
    a failure, so asking must not raise.
    """
    if explicit:
        return explicit

    # `.env` fills gaps in the environment rather than overriding it.
    if env is None:
        load_dotenv()
        env = os.environ

    return env.get(ENV_VAR) or None


def resolve_key(
    explicit: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return the first key found, or refuse with somewhere to get one."""
    if key := find_key(explicit, env=env):
        return key

    raise UsageError(_GUIDANCE)
