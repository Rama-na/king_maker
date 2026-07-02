import io
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def zip_bytes(csv_path: Path) -> bytes:
    """NSE serves bhavcopies as single-CSV zips; build one from a fixture CSV."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(csv_path.name, csv_path.read_bytes())
    return buf.getvalue()


@pytest.fixture
def udiff_cm_zip() -> bytes:
    return zip_bytes(FIXTURES / "udiff_cm_sample.csv")


@pytest.fixture
def legacy_cm_zip() -> bytes:
    return zip_bytes(FIXTURES / "legacy_cm_sample.csv")


@pytest.fixture
def udiff_fo_zip() -> bytes:
    return zip_bytes(FIXTURES / "udiff_fo_sample.csv")


@pytest.fixture
def index_csv() -> bytes:
    return (FIXTURES / "ind_close_all_sample.csv").read_bytes()
