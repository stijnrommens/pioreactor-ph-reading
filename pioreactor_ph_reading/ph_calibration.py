# -*- coding: utf-8 -*-
from __future__ import annotations

import typing as t
from datetime import datetime

from pioreactor import structs
from pioreactor.calibrations.registry import CalibrationProtocol
from pioreactor.calibrations.session_flow import (
    SessionStep,
    StepRegistry,
    run_session_in_cli,
    steps,
    fields,
)
from pioreactor.calibrations.structured_session import (
    CalibrationSession,
    utc_iso_timestamp,
)
from pioreactor.utils.timing import current_utc_datetime
from pioreactor.whoami import get_unit_name


#
# ---- Calibration record -----------------------------------------------------
#

class PHBufferCalibration(structs.CalibrationBase, kw_only=True, tag="ph_buffer"):
    """
    Simple buffer‑based pH calibration.

    We assume a linear model mapping measured voltage → pH.
    """

    x: str = "Voltage"
    y: str = "pH"

    buffer_solutions: list[float]
    electrode_type: str = "unknown"


def _new_calibration_name() -> str:
    return f"ph_buffer_{utc_iso_timestamp().replace(':','').replace('-','')}"


def _poly_identity() -> structs.PolyFitCoefficients:
    # y = 1*x + 0 (placeholder; real fit could be added later)
    return structs.PolyFitCoefficients([1.0, 0.0])


#
# ---- Session steps -----------------------------------------------------------
#

class Intro(SessionStep):
    step_id = "intro"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.info(
            "pH buffer calibration",
            "\n".join(
                [
                    "This protocol calibrates a pH probe using buffer solutions.",
                    "",
                    "You will manually enter the measured voltage and known buffer pH.",
                    "",
                    "Press Continue to begin.",
                ]
            ),
        )

    def advance(self, ctx):
        ctx.data["points"] = []
        return Measure()


class Measure(SessionStep):
    step_id = "measure"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.form(
            "Record buffer measurement",
            "Enter the measured voltage and the known buffer pH value.",
            [
                fields.float("voltage", label="Measured voltage", minimum=-5, maximum=5),
                fields.float("ph", label="Buffer pH", minimum=0, maximum=14),
                fields.bool("add_another", label="Add another buffer?", default=False),
            ],
        )

    def advance(self, ctx):
        voltage = ctx.inputs.float("voltage")
        ph_value = ctx.inputs.float("ph")
        add_another = ctx.inputs.bool("add_another", default=False)

        ctx.data["points"].append({"x": voltage, "y": ph_value})

        if add_another:
            return Measure()
        return Finalize()


class Finalize(SessionStep):
    step_id = "finalize"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.action(
            "Finalize and save",
            "Press Continue to save the pH calibration.",
        )

    def advance(self, ctx):
        points: list[dict[str, float]] = ctx.data.get("points", [])
        if len(points) < 1:
            raise ValueError("At least one calibration point is required.")

        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]

        calibration = PHBufferCalibration(
            calibration_name=_new_calibration_name(),
            calibrated_on_pioreactor_unit=get_unit_name(),
            created_at=current_utc_datetime(),
            curve_data_=_poly_identity(),
            recorded_data={"x": xs, "y": ys},
            buffer_solutions=ys,
            electrode_type="epoxy",
        )

        link = ctx.store_calibration(calibration, "ph")
        ctx.complete({"calibration": link})
        return None


#
# ---- Step registry -----------------------------------------------------------
#

PH_STEPS: StepRegistry = {
    Intro.step_id: Intro,
    Measure.step_id: Measure,
    Finalize.step_id: Finalize,
}


#
# ---- Session + protocol ------------------------------------------------------
#

def start_ph_buffer_session(target_device: str) -> CalibrationSession:
    now = utc_iso_timestamp()
    return CalibrationSession(
        session_id=_new_calibration_name(),
        protocol_name="buffer_based",
        target_device=target_device,
        status="in_progress",
        step_id=Intro.step_id,
        data={},
        created_at=now,
        updated_at=now,
    )


class BufferBasedPHProtocol(CalibrationProtocol[str]):
    target_device = "ph"
    protocol_name = "buffer_based"
    title = "pH calibration (buffer entry)"
    description = "Calibrate a pH probe by manually entering voltage and buffer pH values."
    step_registry = PH_STEPS
    priority = 80

    @classmethod
    def start_session(cls, target_device: str) -> CalibrationSession:
        return start_ph_buffer_session(target_device)

    def run(self, target_device: str) -> structs.CalibrationBase:
        session = start_ph_buffer_session(target_device)
        calibrations = run_session_in_cli(self.step_registry, session)
        if not calibrations:
            raise RuntimeError("No calibration was produced.")
        return t.cast(structs.CalibrationBase, calibrations[-1])


#
# ---- CLI helper --------------------------------------------------------------
#

def run_ph_buffer_session_cli():
    session = start_ph_buffer_session("ph")
    return run_session_in_cli(PH_STEPS, session)
