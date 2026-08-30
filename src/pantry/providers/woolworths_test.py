"""The Woolworths reference shape before its Phase 2 reader exists."""

import pytest

from pantry.open_food_facts import RemoteFailure
from pantry.providers import AcquireOptions, Reference
from pantry.providers.woolworths import WoolworthsProvider


def test_the_stub_claims_woolworths_references() -> None:
    assert WoolworthsProvider.name == "woolworths"
    assert WoolworthsProvider.acquirable


def test_acquisition_states_that_the_reader_is_not_built() -> None:
    reference = Reference("woolworths", "woolworths", "6026666")

    with pytest.raises(RemoteFailure, match="not implemented"):
        WoolworthsProvider().acquire(reference, AcquireOptions())
