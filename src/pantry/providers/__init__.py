"""Sources of product records, behind one interface.

Every source answers at most two questions — "what matches this" and "give me
exactly this" — so the CLI needs four verbs, not one command per source.
Capability is a flag rather than a raised error because the fan-out decides who
to ask before asking, and an unconfigured provider drops out with no message:
being unconfigured is not a failure.
"""

from dataclasses import dataclass

from agentcli import UsageError

from pantry.ids import normalize_id
from pantry.products import Product
from pantry.sites import product_ref
from pantry.woolworths import PRODUCT_URL as WOOLWORTHS_PRODUCT_URL

# Network sources with a live name search. The local store is the default.
SEARCH_SOURCES = ("coles", "umall", "woolworths")

# Who claims which stable identifier prefix. `usda:` names an identifier USDA
# owns, and so do the two retailer forms below. A GTIN does not: it is printed
# on the pack and every source here may publish the same one, so the prefix
# names the code, and Open Food Facts is simply the only provider that can
# resolve one today.
_PREFIXES = {
    "usda": "usda",
    "barcode": "openfoodfacts",
}

REF_FORMS = (
    "coles:<url>, woolworths:<stockcode>, usda:<fdcId>, or barcode:<barcode>"
)


@dataclass(frozen=True)
class Reference:
    """One thing to acquire, resolved to the identity it will be stored under.

    `provider` is who will be asked; `source` and `id` are the pantry identity
    the local store is checked against before anything is spent.
    """

    provider: str
    source: str
    id: str
    url: str | None = None


@dataclass(frozen=True)
class AcquireOptions:
    """Everything an acquire may be told. Each provider reads what it needs."""

    browser: bool = False
    budget: int | None = None
    api_key: str | None = None


class Provider:
    """One source of product records. Subclasses declare what they can do."""

    name = ""

    searchable = False
    acquirable = False

    @property
    def enabled(self) -> bool:
        """False only when a credential this provider needs is absent."""
        return True

    def search(self, query: str, limit: int) -> list[dict]:
        raise NotImplementedError(f"{self.name} cannot search")

    def acquire(self, ref: Reference, options: AcquireOptions) -> Product:
        raise NotImplementedError(f"{self.name} cannot acquire")

    def report(self) -> list[str]:
        """What must be said about this run, successful or not."""
        return []

    def close(self) -> None:
        """Release whatever an acquire opened."""


class Providers:
    """The providers one run may use, addressed by name."""

    def __init__(self, providers: list[Provider]) -> None:
        self._by_name = {provider.name: provider for provider in providers}

    def get(self, name: str) -> Provider:
        provider = self._by_name.get(name)
        if provider is None:
            raise UsageError(f"no provider named {name}")
        return provider

    def searchers(self, *, source: str | None = None) -> list[Provider]:
        """The local store, or the one live source explicitly requested."""
        provider = self._by_name.get(source or "local")
        if provider is None or not provider.searchable or not provider.enabled:
            return []

        return [provider]


def resolve_reference(ref: str) -> Reference:
    """Decide which provider claims a reference, and what identity it names."""
    text = ref.strip()

    # A url names its own source, so the site readers decide which it is.
    if text.startswith(("http://", "https://")):
        site = product_ref(text)
        return Reference("retailer", site.source, site.id, site.url)

    # Coles has no stable short id outside its URL, so the prefix labels the
    # same URL form without trying to reinterpret the address after its colon.
    if text.lower().startswith("coles:"):
        url = text[len("coles:") :].strip()
        site = product_ref(url)
        if site.source != "coles":
            raise UsageError(f"{ref!r} is not {REF_FORMS}")
        return Reference("retailer", site.source, site.id, site.url)

    if text.lower().startswith("woolworths:"):
        stockcode = normalize_id(text[len("woolworths:") :])
        if not stockcode.isdigit():
            raise UsageError(
                "a Woolworths reference is woolworths:<stockcode>, digits only"
            )
        url = WOOLWORTHS_PRODUCT_URL.format(stockcode)
        return Reference("retailer", "woolworths", stockcode, url)

    prefix, _, value = text.partition(":")
    provider = _PREFIXES.get(prefix.lower())
    identifier = normalize_id(value)
    if not provider or not identifier:
        raise UsageError(f"{ref!r} is not {REF_FORMS}")

    if provider == "usda" and not identifier.isdigit():
        raise UsageError("a USDA reference is usda:<fdcId>, digits only")

    # Stored under the provider's name: `manual` would claim the user read it.
    return Reference(provider, provider, identifier)
