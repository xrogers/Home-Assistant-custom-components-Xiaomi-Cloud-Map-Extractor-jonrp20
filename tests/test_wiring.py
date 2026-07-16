import pathlib

CC = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "xiaomi_cloud_map_extractor"


def test_vacuum_xtl_declares_xtl_platform():
    src = (CC / "connector" / "vacuums" / "vacuum_xtl.py").read_text()
    assert "class XtlCloudVacuum(BaseXiaomiCloudVacuumV2)" in src
    assert "return VacuumApi.XTL" in src
    assert "XtlMapDataParser" in src


def test_xtl_registered_in_available_platforms():
    src = (CC / "connector" / "__init__.py").read_text()
    assert "from .vacuums.vacuum_xtl import XtlCloudVacuum" in src
    assert "XtlCloudVacuum," in src  # present in the AVAILABLE_VACUUM_PLATFORMS list literal


def test_manifest_requires_lz4():
    import json
    manifest = json.loads((CC / "manifest.json").read_text())
    assert "lz4" in manifest["requirements"]
