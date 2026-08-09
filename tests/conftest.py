"""
Shared test isolation.

The image index is a *persistent, mutating* store: every claim analysed adds its
fingerprints, and later claims are compared against them. That makes it the first piece of
state in this system where running the test suite can change the behaviour of a production
run — a fixture image indexed by a test would be a standing false accusation against any
real claim resembling it.

So the suite gets its own index, in a temporary directory, discarded afterwards.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_image_index(tmp_path_factory):
    """Point every test at a throwaway image index. Autouse: opting in is too easy to forget."""
    import os

    index_path = tmp_path_factory.mktemp("image_index") / "test_index.db"
    previous = os.environ.get("AURELIX_IMAGE_INDEX")
    os.environ["AURELIX_IMAGE_INDEX"] = str(index_path)
    yield
    if previous is None:
        os.environ.pop("AURELIX_IMAGE_INDEX", None)
    else:
        os.environ["AURELIX_IMAGE_INDEX"] = previous
