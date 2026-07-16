def test_detect_xtl(vacuum_api):
    assert vacuum_api.detect("xtl.vacuum.xm2216") == vacuum_api.XTL


def test_detect_existing_unchanged(vacuum_api):
    assert vacuum_api.detect("viomi.vacuum.v8") == vacuum_api.VIOMI
