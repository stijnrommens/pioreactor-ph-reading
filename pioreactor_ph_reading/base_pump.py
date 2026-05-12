# -*- coding: utf-8 -*-
import json
       
from pioreactor.hardware import PWM_TO_PIN
from pioreactor.utils.pwm import PWM
from pioreactor.utils import clamp
from pioreactor.config import config
from pioreactor.background_jobs.base import BackgroundJobWithDodging
from pioreactor.whoami import get_unit_name, get_latest_experiment_name

class BasePump(BackgroundJobWithDodging):

    published_settings = {
        "duty_cycle": {"datatype": "float", "settable": False, "unit": "%"},
        # "on": {"datatype": "boolean", "settable": True},
    }
    
    job_name="base_pump"

    def __init__(self, hz, initial_duty_cycle, unit, experiment, start_on = True, **kwargs):
        super().__init__(unit=unit, experiment=experiment)
        self.hz = hz
        self._initial_duty_cycle = initial_duty_cycle
        self.duty_cycle = initial_duty_cycle
            
        self.pwm_pin = PWM_TO_PIN[config.get("PWM_reverse", "base_pump")]
        # looks at config.ini/configuration on UI to match 
        # changed PWM channel 3 to "base_pump" on leader
        # whatevers connected to channel 3 will receive power 

        self.pwm = PWM(self.pwm_pin, self.hz)
        self.pwm.lock()

    def set_duty_cycle(self, new_duty_cycle):
        self.duty_cycle = clamp(0, float(new_duty_cycle), 100)
        self.pwm.change_duty_cycle(self.duty_cycle)

    def on_init_to_ready(self):
        self.pwm.start(self.duty_cycle)

    def on_ready_to_sleeping(self):
        self._previous_duty_cycle = self.duty_cycle
        self.set_duty_cycle(0)

    def on_sleeping_to_ready(self):
        self.set_duty_cycle(self._previous_duty_cycle)

    def on_disconnected(self):
        self.logger.debug("disconnecting... will clean up PWM")
        self.pwm.cleanup()
        
    def action_to_do_before_od_reading(self):
        self.set_on(False)
    
    def action_to_do_after_od_reading(self):
        self.set_on(True)
    
import click

@click.command(name="base_pump")
@click.option(
    "--initial-dc",
    default=config.getfloat("base_pump", "initial_duty_cycle"),
    show_default=True,
    type=click.FloatRange(0, 100, clamp=True),
)
@click.option(
    "--hz",
    default=config.getfloat("base_pump", "hz"),
    show_default=True,
    type=click.FloatRange(1, 10_000, clamp=True),
)
def click_base_pump(initial_dc, hz):
    """
    Start the base pump
    """
    job = BasePump(
        hz=hz,
        initial_duty_cycle=initial_dc,
        unit=get_unit_name(),
        experiment=get_latest_experiment_name(),
    )
    job.block_until_disconnected()
    
if __name__ == "__main__":
    click_base_pump()