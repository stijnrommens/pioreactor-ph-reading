# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import suppress

from pioreactor.automations import events
from pioreactor.automations.dosing.base import DosingAutomationJobContrib
from pioreactor.config import config
from pioreactor.pubsub import subscribe
from pioreactor.utils.streaming_calculations import PID


class PHRegulation(DosingAutomationJobContrib):
    automation_name = "ph_regulation"
    published_settings = {
        "target_ph": {"datatype": "float", "settable": True, "unit": "-"}
    }

    def __init__(self, target_ph, **kwargs):
        super(PHRegulation, self).__init__(**kwargs)        
        self.target_ph = float(target_ph)

        self.pid = PID(
            Kp=config.getfloat("ph_regulation.config", "Kp"),
            Ki=config.getfloat("ph_regulation.config", "Ki"),
            Kd=config.getfloat("ph_regulation.config", "Kd"),
            setpoint=self.target_ph,
            unit=self.unit,
            experiment=self.experiment,
            job_name=self.job_name,
            target_name="ph",
            output_limits=(0, 100),
        )

    def execute(self):
        actual_ph = subscribe(f"pioreactor/{self.unit}/{self.experiment}/ph_reading/ph", timeout=1)

        if actual_ph is not None:
            actual_ph = float(actual_ph.payload.decode())
            dosing_time = self.pid.update(actual_ph, dt=self.duration/60)
            if actual_ph < self.min_ph:
                dur = self.add_alt_media_to_bioreactor(
                    duration=dosing_time,
                    source_of_event=f"{self.job_name}:{self.automation_name}",
                    unit=self.unit,
                    experiment=self.experiment,
                    mqtt_client=self.pub_client,
                    logger=self.logger,
                )
        else:
            actual_ph = None

    @property
    def min_ph(self):
        return 0.95 * self.target_ph
    
    @property
    def max_ph(self):
        return 1.05 * self.target_ph
