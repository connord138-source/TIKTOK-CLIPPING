"""Every test runs against a throwaway farm root (config copied, empty data) — never the repo's data/."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_tmp = Path(tempfile.mkdtemp(prefix="clipfarm-test-"))
shutil.copytree(REPO / "config", _tmp / "config")
(_tmp / "data").mkdir()
os.environ["CLIPFARM_ROOT"] = str(_tmp)
sys.path.insert(0, str(REPO))

import pytest  # noqa: E402

from clipfarm.core import Store, write_json  # noqa: E402


@pytest.fixture(autouse=True)
def clean_store():
    for p in (Store.clips, Store.candidates):
        write_json(p, [])
    write_json(Store.metrics, {"account": [], "videos": {}})
    yield


@pytest.fixture
def farm_root():
    return _tmp
