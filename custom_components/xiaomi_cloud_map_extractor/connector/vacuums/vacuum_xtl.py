from typing import Self

from .base.model import VacuumConfig, VacuumApi
from .base.vacuum_v2 import BaseXiaomiCloudVacuumV2
from .map_parser_xtl import XtlMapDataParser


class XtlCloudVacuum(BaseXiaomiCloudVacuumV2):
    _xtl_map_data_parser: XtlMapDataParser

    def __init__(self: Self, vacuum_config: VacuumConfig) -> None:
        super().__init__(vacuum_config)
        self._xtl_map_data_parser = XtlMapDataParser(
            vacuum_config.palette,
            vacuum_config.sizes,
            vacuum_config.drawables,
            vacuum_config.image_config,
            vacuum_config.texts,
        )

    @staticmethod
    def vacuum_platform() -> VacuumApi:
        return VacuumApi.XTL

    @property
    def map_archive_extension(self: Self) -> str:
        return "json"

    @property
    def map_data_parser(self: Self) -> XtlMapDataParser:
        return self._xtl_map_data_parser
