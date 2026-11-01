"""Smoke tests for the installed package."""

from importlib.metadata import metadata

import snfutil


def test_package_is_importable():
    assert snfutil.__name__ == "snfutil"


def test_distribution_metadata():
    package_metadata = metadata("snfutil")
    assert package_metadata["Name"] == "snfutil"
    assert package_metadata["Version"]
