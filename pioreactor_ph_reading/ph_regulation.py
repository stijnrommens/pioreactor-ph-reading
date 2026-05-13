# -*- coding: utf-8 -*-
from __future__ import annotations

import click
from pioreactor_ph_reading.base_pump import BasePump, click_base_pump
from pioreactor_ph_reading.ph_reading import PHReading, click_ph_reading

from pioreactor.background_jobs.base import BackgroundJobContrib
from pioreactor.utils.streaming_calculations import PID
from pioreactor.config import config
from pioreactor.cli.run import run
from pioreactor.utils import clamp
from pioreactor.whoami import get_assigned_experiment_name
from pioreactor.whoami import get_unit_name


class PHRegulation(BackgroundJobContrib):
    job_name = "ph_regulation"
    published_settings = {
        "ph_setpoint": {"datatype": "float", "unit": "-", "settable": True},
    }

    def __init__(self, ph_setpoint:float, **kwargs) -> None:
        super().__init__(**kwargs)
        self.logger.warning("When supplying base, no liquid is removed. Carefully monitor the level of liquid to avoid overflow!")
        # self.pid = PID(
        #     Kp=config.getfloat("ph_regulation.config", "Kp"),
        #     Ki=config.getfloat("ph_regulation.config", "Ki"),
        #     Kd=config.getfloat("ph_regulation.config", "Kd"),
        #     setpoint=None,
        #     unit=self.unit,
        #     experiment=self.experiment,
        #     job_name=self.job_name,
        #     target_name="ph",
        #     output_limits=(-2.5, 2.5),
        #     derivative_smoothing=0.925,
        #     pub_client=self.pub_client,
        # )
        self.set_ph_setpoint(ph_setpoint)

    def _clamp_ph_setpoint(self, ph_setpoint: float) -> float:
        return clamp(0.0, ph_setpoint, 14.0)
    
    def set_ph_setpoint(self, ph_setpoint:float) -> None:
        ph_setpoint = float(ph_setpoint)
        self.ph_setpoint = self._clamp_ph_setpoint(ph_setpoint)
        # self.pid.set_setpoint(self.ph_setpoint)

    def execute(self):
        if self.click_ph_reading() < self.ph_setpoint:
            self.click_base_pump()



@run.command(name="ph_regulation")
def click_ph_regulation() -> None:
    """
    Controls pH by automatic base dosing.
    """
    unit = get_unit_name()
    job = PHRegulation(
        unit=unit,
        experiment=get_assigned_experiment_name(unit),
    )
    job.execute()