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


@pytest.fixture(autouse=True)
def _isolated_image_index(tmp_path_factory):
    """
    A throwaway image index **per test**. Autouse, because opting in is too easy to forget.

    Per test rather than per session, learned the hard way: two tests generating a photo
    from the same random seed produce byte-identical images, so the second one matched the
    first as a reused photograph and came back `contradicted` instead of `supported` — a
    failure that appeared only in the full suite and never in isolation. The detector was
    right; the shared index was the bug.
    """
    import os

    index_path = tmp_path_factory.mktemp("image_index") / "test_index.db"
    previous = os.environ.get("AURELIX_IMAGE_INDEX")
    os.environ["AURELIX_IMAGE_INDEX"] = str(index_path)
    yield
    if previous is None:
        os.environ.pop("AURELIX_IMAGE_INDEX", None)
    else:
        os.environ["AURELIX_IMAGE_INDEX"] = previous


@pytest.fixture(autouse=True)
def _isolated_upload_dir(tmp_path_factory):
    """
    Uploads land in a temporary directory too.

    Claim photographs are now persisted so the review screen can display the evidence a
    verdict was based on. That makes the upload directory the second mutating store the
    suite could contaminate: without this, every test submission would leave a fixture
    image sitting in the folder the production API serves from.
    """
    import os

    target = tmp_path_factory.mktemp("uploads")
    previous = os.environ.get("UPLOAD_DIR")
    os.environ["UPLOAD_DIR"] = str(target)
    yield
    if previous is None:
        os.environ.pop("UPLOAD_DIR", None)
    else:
        os.environ["UPLOAD_DIR"] = previous
