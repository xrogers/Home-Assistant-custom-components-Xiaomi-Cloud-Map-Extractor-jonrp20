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


def test_no_lz4_dependency_pure_python():
    # HA OS has no C toolchain, so the compiled `lz4` package can't be built
    # there. LZ4 decompression is done in pure Python instead, so the manifest
    # must NOT require lz4 and the parser must not import it.
    import json
    manifest = json.loads((CC / "manifest.json").read_text())
    assert not any("lz4" in req.lower() for req in manifest["requirements"])
    parser_src = (CC / "connector" / "vacuums" / "map_parser_xtl.py").read_text()
    assert "import lz4" not in parser_src
    assert "def lz4_decompress_block" in parser_src
