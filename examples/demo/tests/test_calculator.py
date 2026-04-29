import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from calculator import add, multiply


def test_add_positive():
    assert add(1, 2) == 3


def test_add_zero():
    assert add(0, 5) == 5


def test_add_negative():
    assert add(-3, 8) == 5


def test_multiply():
    assert multiply(3, 4) == 12
