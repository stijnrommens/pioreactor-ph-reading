from __future__ import annotations

import typing as t
import logging
from datetime import datetime
from pioreactor_ph_reading.atlas_ezo_ph import AtlasEzoPH

from pioreactor.calibrations import CalibrationProtocol
from pioreactor.structs import CalibrationBase
from pioreactor.utils.timing import current_utc_datetime
from pioreactor import whoami
from pioreactor.calibrations.session_flow import SessionStep
from pioreactor.calibrations.session_flow import StepRegistry
from pioreactor.calibrations.session_flow import run_session_in_cli
from pioreactor.calibrations.session_flow import steps, fields
from pioreactor.calibrations.structured_session import CalibrationSession
from pioreactor.calibrations.structured_session import utc_iso_timestamp

class PHBufferCalibration(CalibrationBase, kw_only=True, tag="ph_buffer"):
    x: str = "pH"
    y: str = "Voltage"

    buffer_solution: t.Literal["4.01", "7.00"]
    electrode_type: str

    def voltage_to_ph(self, voltage: float):
        return self.y_to_x(voltage)

    def ph_to_voltage(self, ph: float):
        return self.x_to_y(ph)
    
def get_signal(ctx, *, cmd: str, timeout_s: float):
    probe = AtlasEzoPH.from_config()
    resp = probe.query(cmd, timeout_s=float(timeout_s))
    return {"status_code": resp.status_code, "body": resp.body}

class BufferBasedPHProtocol(CalibrationProtocol):
    target_device = "ph"
    protocol_name = "buffer_based"
    description = "Calibrate the pH sensor using buffer solutions"
    step_registry = PH_STEPS

    @classmethod
    def start_session(cls, target_device: str) -> CalibrationSession:
        return start_ph_buffer_session(target_device)
    step_registry = PH_STEPS

    @classmethod
    def start_session(cls, target_device: str) -> CalibrationSession:
        return start_ph_buffer_session(target_device)

    def run(self, target_device: str):
        return run_ph_buffer_calibration()

def run_ph_buffer_calibration():
    # run the calibration to get data
    ...

    return PHBufferCalibration(
        calibration_name="ph_calibration",
        calibrated_on_pioreactor_unit=whoami.get_unit_name(),
        created_at=current_utc_datetime(),
        curve_data_=[2, 3, 5],
        curve_type="poly",
        x="Voltage",
        y="pH",
        recorded_data={"x": [0.1, 0.2, 0.3], "y": [1.0, 2.0, 3.0]},
        buffer_solution="default",
        electrode_type="glass"
    )

# Session steps (UI + CLI flow)
class Intro(SessionStep):
    step_id = "intro"

    def render(self, ctx):
        return steps.info("pH calibration", "Place probe in buffer.")

    def advance(self, ctx):
        return Measure()

class Measure(SessionStep):
    step_id = "measure"

    def render(self, ctx):
        return steps.form(
            "Measure buffer",
            "Record voltage and pH.",
            [fields.float("voltage", minimum=0), fields.float("ph", minimum=0, maximum=14)],
        )

    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        voltage = get_signal(ctx, cmd="Cal,low,4.00", timeout_s=timeout_s)
        ph_value = ctx.inputs.float("ph", minimum=0, maximum=14)
        calibration = PHBufferCalibration(
            calibration_name="ph_calibration",
            calibrated_on_pioreactor_unit=whoami.get_unit_name(),
            created_at=current_utc_datetime(),
            curve_data_=[1.0, 0.0],
            curve_type="poly",
            x="Voltage",
            y="pH",
            recorded_data={"x": [voltage], "y": [ph_value]},
            buffer_solution="default",
            electrode_type="glass",
        )
        link = ctx.store_calibration(calibration, "ph")
        ctx.complete({"calibration": link})
        return None

PH_STEPS: StepRegistry = {
    Intro.step_id: Intro,
    Measure.step_id: Measure,
}

def start_ph_buffer_session(target_device: str) -> CalibrationSession:
    now = utc_iso_timestamp()
    return CalibrationSession(
        session_id="...",
        protocol_name="buffer_based",
        target_device=target_device,
        status="in_progress",
        step_id=Intro.step_id,
        data={},
        created_at=now,
        updated_at=now,
    )


def run_ph_buffer_session_cli():
    session = start_ph_buffer_session("ph")
    return run_session_in_cli(PH_STEPS, session)
