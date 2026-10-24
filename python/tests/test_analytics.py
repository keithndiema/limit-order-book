import numpy as np
import pytest

from lob import analytics as an


def test_ofi_signs():
    # bid size grows at same price -> buying pressure; ask size grows at same price -> selling pressure
    e = an.order_flow_imbalance([100, 100], [10, 15], [101, 101], [10, 10])
    assert e[1] == 5
    e = an.order_flow_imbalance([100, 100], [10, 10], [101, 101], [10, 14])
    assert e[1] == -4
    # bid price improves -> +new bid size (nothing was ever at the new level to subtract)
    e = an.order_flow_imbalance([100, 101], [10, 7], [102, 102], [5, 5])
    assert e[1] == 7


def test_ols_recovers_slope():
    rng = np.random.default_rng(0)
    x = rng.normal(size=5000)
    y = 2.0 + 0.7 * x + rng.normal(scale=0.1, size=5000)
    r = an.ols(x, y)
    assert r["slope"] == pytest.approx(0.7, abs=0.01)
    assert r["intercept"] == pytest.approx(2.0, abs=0.01)
    assert r["r2"] > 0.95 and r["t"] > 100


def test_acf_white_noise_and_ar1():
    rng = np.random.default_rng(1)
    w = rng.normal(size=20000)
    a = an.acf(w, 5)
    assert a[0] == 1 and np.all(np.abs(a[1:]) < 0.03)
    x = np.zeros(20000)
    for i in range(1, len(x)):
        x[i] = 0.6 * x[i - 1] + w[i]
    assert an.acf(x, 1)[1] == pytest.approx(0.6, abs=0.03)


def test_max_drawdown():
    assert an.max_drawdown([0, 5, 3, 8, 2, 9]) == 6
    assert an.max_drawdown([]) == 0.0
