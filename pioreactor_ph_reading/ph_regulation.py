# -*- coding: utf-8 -*-
from __future__ import annotations

from pioreactor.automations.dosing.base import DosingAutomationJobContrib
from pioreactor.pubsub import subscribe


class PHRegulation(DosingAutomationJobContrib):
    automation_name = "ph_regulation"
    published_settings = {
        "dosing_volume": {"datatype": "float", "settable": True, "unit": "mL"},
        "target_ph": {"datatype": "float", "settable": True, "unit": "-"}
    }

    def __init__(self, dosing_volume, target_ph, **kwargs):
        super().__init__(**kwargs)
        self.logger.warning("When using pH control, no liquid is removed. Carefully monitor the level of liquid to avoid overflow!")
        self.dosing_volume = float(dosing_volume)
        self.target_ph     = float(target_ph)

    def execute(self):
        actual_ph = subscribe(f"pioreactor/{self.unit}/{self.experiment}/ph_reading/ph", timeout=1)
        if actual_ph is not None:
            actual_ph = actual_ph.payload.decode() # this is now a string, you may need to call float(...) etc to convert it. 
        else:
            actual_ph = None
        if actual_ph < (self.target_ph - 0.1):
            vol = self.add_alt_media_to_bioreactor(
                ml=self.dosing_volume,
                source_of_event=f"{self.job_name}:{self.automation_name}",
                unit=self.unit,
                experiment=self.experiment,
                mqtt_client=self.pub_client,
                logger=self.logger,
            )
            if vol != self.dosing_volume:
                self.logger.warning("Under-dosed!")