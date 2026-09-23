"""Generate a small shop project that exercises ACCO's two savings paths.

* ``shop/catalog.py`` is a ~700-line module. An agent that Reads it whole pays
  for every line on every later turn; ACCO answers with an outline.
* ``make check`` runs the suite, and ``pytest.ini`` sets ``-v`` (a common CI-style
  default), so one run prints ~630 lines. ACCO keeps the failure and the summary and trims the rest.

There is one real bug: ordering exactly ``BULK_THRESHOLD`` units gets no bulk
discount (``>`` should be ``>=``). Everything else passes.
"""

from __future__ import annotations

from pathlib import Path

ZONES = 40
WEIGHTS = (0.5, 1, 2, 3, 5, 8, 10, 15, 20, 25, 30, 40, 50, 75, 100)
BUGGY_LINE = "    if quantity > BULK_THRESHOLD:"
FIXED_LINE = "    if quantity >= BULK_THRESHOLD:"

PROMPT = (
    "CI is red: `make check` fails. Customers also report that ordering exactly "
    "10 units of an item does not get the bulk discount, but 11 units does. "
    "Find and fix the cause, then run `make check` again to confirm it passes, "
    "and reply with one sentence describing the change."
)

HIDDEN_TEST = '''from shop.catalog import BULK_RATE, BULK_THRESHOLD, bulk_discount


def test_threshold_quantity_is_discounted():
    assert bulk_discount(BULK_THRESHOLD, 20.0) == round(BULK_THRESHOLD * 20.0 * (1 - BULK_RATE), 2)


def test_below_threshold_is_not_discounted():
    assert bulk_discount(BULK_THRESHOLD - 1, 20.0) == (BULK_THRESHOLD - 1) * 20.0


def test_well_above_threshold_is_discounted():
    assert bulk_discount(100, 3.5) == round(100 * 3.5 * (1 - BULK_RATE), 2)
'''


def _zone_function(zone: int) -> str:
    return f'''

def shipping_zone_{zone:02d}(weight_kg):
    """Shipping cost in USD for zone {zone:02d}.

    Zone {zone:02d} charges a flat base plus a per-kilogram rate. Parcels above
    the heavy threshold pay a surcharge on the excess weight only.
    """
    if weight_kg <= 0:
        raise ValueError("weight must be positive")
    base = {_base(zone)}
    per_kg = {_per_kg(zone)}
    heavy_threshold = 20
    cost = base + per_kg * weight_kg
    if weight_kg > heavy_threshold:
        cost += 0.5 * (weight_kg - heavy_threshold)
    return round(cost, 2)
'''


def _base(zone: int) -> float:
    return round(4.5 + 0.25 * zone, 2)


def _per_kg(zone: int) -> float:
    return round(0.8 + 0.02 * zone, 2)


BULK = f'''

BULK_THRESHOLD = 10
BULK_RATE = 0.10


def bulk_discount(quantity, unit_price):
    """Total price for ``quantity`` units; 10% off once the threshold is reached."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    total = quantity * unit_price
{BUGGY_LINE}
        total *= 1 - BULK_RATE
    return round(total, 2)
'''


def catalog_source() -> str:
    parts = ['"""Pricing rules for the shop: per-zone shipping and bulk discounts."""\n']
    for zone in range(1, ZONES + 1):
        parts.append(_zone_function(zone))
        if zone == ZONES // 2:
            parts.append(BULK)
    table = ",\n".join(f"    {z}: shipping_zone_{z:02d}" for z in range(1, ZONES + 1))
    parts.append(f"\n\nSHIPPING = {{\n{table},\n}}\n")
    return "".join(parts)


TEST_SHIPPING = f'''import pytest

from shop.catalog import SHIPPING

WEIGHTS = {WEIGHTS!r}


def expected(zone, weight):
    cost = round(4.5 + 0.25 * zone, 2) + round(0.8 + 0.02 * zone, 2) * weight
    if weight > 20:
        cost += 0.5 * (weight - 20)
    return round(cost, 2)


@pytest.mark.parametrize("zone", sorted(SHIPPING))
@pytest.mark.parametrize("weight", WEIGHTS)
def test_shipping_cost(zone, weight):
    assert SHIPPING[zone](weight) == expected(zone, weight)
'''

TEST_BULK = '''import pytest

from shop.catalog import BULK_RATE, BULK_THRESHOLD, bulk_discount


@pytest.mark.parametrize("quantity", [1, 5, 9])
def test_no_discount_below_threshold(quantity):
    assert bulk_discount(quantity, 12.5) == round(quantity * 12.5, 2)


@pytest.mark.parametrize("quantity", [11, 20, 50])
def test_discount_above_threshold(quantity):
    assert bulk_discount(quantity, 12.5) == round(quantity * 12.5 * (1 - BULK_RATE), 2)


def test_discount_at_threshold():
    assert bulk_discount(BULK_THRESHOLD, 12.5) == round(BULK_THRESHOLD * 12.5 * (1 - BULK_RATE), 2)
'''


def make_project(dest: Path) -> Path:
    """Write the demo project into ``dest`` and return it."""
    dest = Path(dest)
    (dest / "shop").mkdir(parents=True, exist_ok=True)
    (dest / "tests").mkdir(parents=True, exist_ok=True)
    (dest / "shop" / "__init__.py").write_text("", encoding="utf-8")
    (dest / "shop" / "catalog.py").write_text(catalog_source(), encoding="utf-8")
    (dest / "tests" / "test_shipping.py").write_text(TEST_SHIPPING, encoding="utf-8")
    (dest / "tests" / "test_bulk.py").write_text(TEST_BULK, encoding="utf-8")
    (dest / "conftest.py").write_text("", encoding="utf-8")
    (dest / "Makefile").write_text("check:\n\tpython3 -m pytest\n", encoding="utf-8")
    (dest / "pytest.ini").write_text("[pytest]\naddopts = -v\ntestpaths = tests\n", encoding="utf-8")
    return dest
