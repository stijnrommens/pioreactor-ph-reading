# -*- coding: utf-8 -*-
from __future__ import annotations

from pioreactor.automations.dosing.base import DosingAutomationJobContrib
from pioreactor.pubsub import subscribe


class PHRegulation(DosingAutomationJobContrib):
    automation_name = "ph_regulation"
    published_settings = {
        "dosing_time": {"datatype": "float", "settable": True, "unit": "s"},
        "target_ph": {"datatype": "float", "settable": True, "unit": "-"}
    }

    def __init__(self, dosing_time, target_ph, **kwargs):
        super().__init__(**kwargs)
        self.logger.warning("When using pH control, no liquid is removed. Carefully monitor the level of liquid to avoid overflow!")
        self.dosing_time = float(dosing_time)
        self.target_ph   = float(target_ph)

    def execute(self):
        actual_ph = subscribe(f"pioreactor/{self.unit}/{self.experiment}/ph_reading/ph", timeout=1)
        if actual_ph is not None:
            actual_ph = actual_ph.payload.decode()
            if float(actual_ph) < (self.target_ph - 0.1):
                dur = self.add_alt_media_to_bioreactor(
                    duration=self.dosing_time,
                    source_of_event=f"{self.job_name}:{self.automation_name}",
                    unit=self.unit,
                    experiment=self.experiment,
                    mqtt_client=self.pub_client,
                    logger=self.logger,
                )
        else:
            actual_ph = None
