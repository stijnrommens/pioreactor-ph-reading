# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import click
import busio
from time import sleep
from pioreactor_ph_reading.atlas_ezo_ph import AtlasEzoPH

from pioreactor.background_jobs.base import BackgroundJobContrib
from pioreactor.background_jobs.leader.mqtt_to_db_streaming import produce_metadata
from pioreactor.background_jobs.leader.mqtt_to_db_streaming import register_source_to_sink
from pioreactor.background_jobs.leader.mqtt_to_db_streaming import TopicToParserToTable
from pioreactor.cli.run import run
from pioreactor.config import config
from pioreactor.exc import HardwareNotFoundError
from pioreactor.hardware import get_scl_pin
from pioreactor.hardware import get_sda_pin
from pioreactor.utils import timing
from pioreactor.whoami import get_assigned_experiment_name
from pioreactor.whoami import get_unit_name
from pioreactor.whoami import is_testing_env

def __dir__():
    return ['click_ph_reading']

def parser(topic, payload) -> dict:
    metadata = produce_metadata(topic)
    return {
        "experiment": metadata.experiment,
        "pioreactor_unit": metadata.pioreactor_unit,
        "timestamp": timing.current_utc_timestamp(),
        "ph_reading": float(payload),
    }


register_source_to_sink(
    TopicToParserToTable(
        ["pioreactor/+/+/ph_reading/ph"],
        parser,
        "ph_readings",
    )
)


class PHReading(BackgroundJobContrib):
    job_name = "ph_reading"
    published_settings = {
        "interval": {"datatype": "float", "unit": "s", "settable": True},
        "ph": {"datatype": "float", "unit": "-", "settable": False},
    }

    def __init__(self, unit:str, experiment:str, **kwargs) -> None:
        super().__init__(unit=unit, experiment=experiment, plugin_name="pioreactor_ph_reading", **kwargs)

        self.interval = config.getfloat(f"{self.job_name}.config", "interval")
        self.probe = AtlasEzoPH.from_config()
        self.record_ph_timer = timing.RepeatedTimer(self.interval,self.record_from_ph,run_immediately=True).start()

    def record_from_ph(self):
        self.ph = float(self.probe.read_ph(samples=2))
        return self.ph
      
    def set_interval(self, new_interval) -> None:
        self.record_ph_timer.interval = new_interval
        self.interval = new_interval

    def on_sleeping(self) -> None:
        self.record_ph_timer.pause()

    def on_ready_to_sleeping(self) -> None:
        self.timer_thread.pause()

    def on_sleeping_to_ready(self) -> None:
        self.record_ph_timer.unpause()

    def on_disconnected(self) -> None:
        self.record_ph_timer.cancel()


@run.command(name="ph_reading")
def click_ph_reading() -> None:
    """
    Returns pH readings.
    """
    unit = get_unit_name()
    job = PHReading(
        unit=unit,
        experiment=get_assigned_experiment_name(unit),
    )
    job.block_until_disconnected()
