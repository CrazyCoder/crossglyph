import pytest

import fontpaths


@pytest.fixture
def noto_or_skip():
    """The firmware's own NotoSans, from a checkout beside this one.

    Almost every test synthesizes its faces. These few need real outlines and
    real metrics, and they assert this face's in particular.
    """
    path = fontpaths.noto()
    if path is None:
        pytest.skip(f"{fontpaths.FIRMWARE_TTF} not found "
                    f"(no firmware checkout beside this one)")
    return path
