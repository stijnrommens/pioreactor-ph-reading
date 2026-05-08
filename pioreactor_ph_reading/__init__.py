# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import click
import busio
from time import sleep

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

    def __init__(
        self,
        unit: str,
        experiment: str,
    ) -> None:
        super().__init__(unit=unit, experiment=experiment, plugin_name="pioreactor_ph_reading")

        self.interval = config.getfloat(f"{self.job_name}.config", "interval")

        self.i2c_channel = int(config.get("ph_reading.config", "i2c_channel_hex"), base=16)
        self.i2c = busio.I2C(3, 2)

        self.record_ph_timer = timing.RepeatedTimer(
            self.interval,
            self.record_from_ph,
            run_immediately=True,
        )
        self.record_ph_timer.start()

    def record_from_ph(self):
        samples = 2
        running_sum = 0.0
        for _ in range(samples):
            running_sum += self.query("R")
            sleep(0.05)
        self.pH = running_sum/samples
        return self.pH
      
    def set_interval(self, new_interval) -> None:
        self.record_ph_timer.interval = new_interval
        self.interval = new_interval

    def on_sleeping(self) -> None:
        # user pauses
        self.record_ph_timer.pause()

    def on_sleeping_to_ready(self) -> None:
        self.record_ph_timer.unpause()

    def on_disconnected(self) -> None:
        self.record_ph_timer.cancel()

    def write(self, cmd):
        cmd_bytes = bytes(cmd + "\x00", "latin-1")  # Null-terminated command
        self.i2c.writeto(self.i2c_channel, cmd_bytes)

    @staticmethod
    def handle_raspi_glitch(response):
        return [chr(x & ~0x80) for x in response]

    def read(self, num_of_bytes=31):
        result = bytearray(num_of_bytes)
        self.i2c.readfrom_into(self.i2c_channel, result)
        response = self.get_response(result)
        char_list = self.handle_raspi_glitch(response[1:])
        return float(''.join(char_list))

    def query(self, command):
        self.write(command)
        current_timeout = 1.5
        sleep(current_timeout)
        return self.read()

    @staticmethod
    def get_response(raw_data):
        return [i for i in raw_data if i != 0]


@run.command(name="ph_reading")
def start_ph_reading() -> None:
    """
    Returns pH readings.
    """
    unit = get_unit_name()
    job = PHReading(
        unit=unit,
        experiment=get_assigned_experiment_name(unit),
    )
    job.block_until_disconnected()
