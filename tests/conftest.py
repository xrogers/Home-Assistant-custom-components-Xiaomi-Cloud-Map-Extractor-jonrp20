import base64
import importlib.util
import json
import pathlib
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
CC = REPO / "custom_components" / "xiaomi_cloud_map_extractor"
# make the vendored parser importable in isolation (imports only vacuum_map_parser_base/lz4/PIL)
sys.path.insert(0, str(CC / "connector" / "vacuums"))


def load_base_model():
    """Load connector/vacuums/base/model.py without executing the HA-coupled
    package __init__ chain (which needs aiohttp/homeassistant). We register stub
    parent packages and a stub for the xiaomi_cloud.connector module that
    base/model.py imports only for type annotations."""
    pkg = "custom_components.xiaomi_cloud_map_extractor"

    def fake_pkg(name: str, path: pathlib.Path) -> None:
        if name in sys.modules:
            return
        m = types.ModuleType(name)
        m.__path__ = [str(path)]
        m.__package__ = name
        sys.modules[name] = m

    fake_pkg("custom_components", CC.parent)
    fake_pkg(pkg, CC)
    fake_pkg(f"{pkg}.connector", CC / "connector")
    fake_pkg(f"{pkg}.connector.xiaomi_cloud", CC / "connector" / "xiaomi_cloud")
    fake_pkg(f"{pkg}.connector.vacuums", CC / "connector" / "vacuums")
    fake_pkg(f"{pkg}.connector.vacuums.base", CC / "connector" / "vacuums" / "base")

    conn_name = f"{pkg}.connector.xiaomi_cloud.connector"
    if conn_name not in sys.modules:
        conn = types.ModuleType(conn_name)
        conn.XiaomiCloudConnector = type("XiaomiCloudConnector", (), {})
        conn.XiaomiCloudDeviceInfo = type("XiaomiCloudDeviceInfo", (), {})
        sys.modules[conn_name] = conn

    mod_name = f"{pkg}.connector.vacuums.base.model"
    spec = importlib.util.spec_from_file_location(
        mod_name, CC / "connector" / "vacuums" / "base" / "model.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vacuum_api():
    return load_base_model().VacuumApi


@pytest.fixture
def raw_map_bytes() -> bytes:
    diag = json.loads((pathlib.Path(__file__).parent / "fixtures" / "diagnostics_p20.json").read_text())
    b64 = diag["data"]["device_data"]["map_data_raw"]
    return base64.b64decode(b64)


@pytest.fixture
def field0(raw_map_bytes) -> dict:
    outer = json.loads(raw_map_bytes)
    return json.loads(base64.b64decode(outer["fields"][0]))
