import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from hid_capture import parse_int
from hid_watch import parse_kwarg


def test_parse_int_accepts_hex():
    assert parse_int("0x0b05") == 0x0b05


def test_parse_int_accepts_decimal():
    assert parse_int("2821") == 2821


def test_parse_kwarg_splits_on_equals():
    assert parse_kwarg("description_match=Arctis Pro Wireless") == (
        "description_match", "Arctis Pro Wireless")


def test_parse_kwarg_requires_equals():
    with pytest.raises(Exception):
        parse_kwarg("no-equals-sign")
