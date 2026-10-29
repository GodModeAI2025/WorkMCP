from __future__ import annotations

from collections.abc import Iterator

import pytest

from workmcp.store import KnowledgeStore


@pytest.fixture
def store() -> Iterator[KnowledgeStore]:
    s = KnowledgeStore(":memory:")
    yield s
    s.close()
