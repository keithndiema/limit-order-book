import pytest

import lob


def _backends():
    return ["python"] + (["cpp"] if lob.HAS_CPP else [])


@pytest.fixture(params=_backends())
def backend(request):
    return request.param


@pytest.fixture
def book(backend):
    return lob.OrderBook(backend=backend)
