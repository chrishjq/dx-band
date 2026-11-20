# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from dxband.version import __version__, release_version_tuple


def test_source_version_uses_fixed_release_number() -> None:
    assert __version__ == "2026.11.10.1"


def test_release_version_ordering() -> None:
    assert release_version_tuple("2026.11.10") < release_version_tuple("2026.11.10.1")
    assert release_version_tuple("2026.11.10.2") > release_version_tuple("2026.11.10.1")


@pytest.mark.parametrize(
    "value", ["261109e07458", "2026.11.10.0", "2026.13.1", "2026.11", "2026.2.30"]
)
def test_release_version_rejects_invalid_numbers(value: str) -> None:
    with pytest.raises(ValueError):
        release_version_tuple(value)
