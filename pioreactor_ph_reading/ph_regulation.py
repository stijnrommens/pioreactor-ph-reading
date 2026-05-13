# -*- coding: utf-8 -*-
from __future__ import annotations

from pioreactor_ph_reading.ph_reading import PHReading, click_ph_reading

# __all__ = ['PHRegulation']


class PHRegulation(DosingAutomationJobContrib):
    automation_name = "ph_regulation"
    published_settings = {
        "dosing_volume": {"datatype": "float", "settable": True, "unit": "mL"},
        "target_ph": {"datatype": "float", "settable": True, "unit": "-"}
    }

    def __init__(self, dosing_volume, target_ph, **kwargs):
        super().__init__(**kwargs)
        self.logger.warning(
            "When using the fed-batch automation, no liquid is removed. Carefully monitor the level of liquid to avoid overflow!"
        )
        self.dosing_volume = float(dosing_volume)
        self.target_ph = float(target_ph)

    def execute(self):
        if self.click_ph_reading() < self.target_ph:
            vol = self.add_media_to_bioreactor(
                ml=self.dosing_volume,
                source_of_event=f"{self.job_name}:{self.automation_name}",
                unit=self.unit,
                experiment=self.experiment,
                mqtt_client=self.pub_client,
                logger=self.logger,
            )
            if vol != self.dosing_volume:
                self.logger.warning("Under-dosed!")