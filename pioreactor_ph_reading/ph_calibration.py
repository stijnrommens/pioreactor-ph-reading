from __future__ import annotations

import typing as t
import logging
from datetime import datetime
from pioreactor_ph_reading.atlas_ezo_ph import AtlasEzoPH

from pioreactor import structs
from pioreactor.calibrations.registry import CalibrationProtocol
from pioreactor.calibrations.session_flow import SessionStep
from pioreactor.calibrations.session_flow import StepRegistry
from pioreactor.calibrations.session_flow import fields
from pioreactor.calibrations.session_flow import steps
from pioreactor.calibrations.structured_session import CalibrationSession
from pioreactor.calibrations.structured_session import utc_iso_timestamp
from pioreactor.utils.timing import current_utc_datetime
from pioreactor.whoami import get_unit_name
from pioreactor.calibrations.session_flow import run_session_in_cli
from pioreactor.web.config import huey
from pioreactor.web.tasks import register_calibration_action


class PHBufferCalibration(structs.CalibrationBase, kw_only=True, tag="ph_buffer"):
    x: str = "pH"
    y: str = "Voltage"

    buffer_solution: t.Literal["4.01", "7.00"]
    electrode_type: str

    def voltage_to_ph(self, voltage: float):
        return self.y_to_x(voltage)

    def ph_to_voltage(self, ph: float):
        return self.x_to_y(ph)
    
def _new_calibration_name() -> str:
    return f"ezo_ph_{utc_iso_timestamp().replace(':', '').replace('-', '')}"

def _poly_identity() -> structs.PolyFitCoefficients:
    return structs.PolyFitCoefficients([1.0, 0.0])

def _build_chart_from_points(points: list[dict[str, float]]) -> dict[str, t.Any]:
    return {
        "title": "pH calibration",
        "x_label": "pH",
        "y_label": "Voltage",
        "series": [
            {
                "id": "ph",
                "label": "Measurements",
                "points": points,
            }
        ],
    }

def _exec_ph_cmd(ctx, *, cmd: str, timeout_s: float) -> dict[str, t.Any]:
    if getattr(ctx, "executor", None) is not None and getattr(ctx, "mode", None) == "ui":
        last_status = 0
        last_body: t.Any = None
        for attempt in range(3):
            payload = ctx.executor("ph_ezo_cmd", {"cmd": cmd, "timeout_s": float(timeout_s)})
            if isinstance(payload, dict):
                last_status = int(payload.get("status_code", 0))
                last_body = payload.get("body")
            if last_status == 1:
                return {"status_code": last_status, "body": last_body}
        return {"status_code": last_status, "body": last_body}
    try:
        probe = AtlasEzoPH.from_config()
        resp = probe.query(cmd, timeout_s=float(timeout_s))
        return {"status_code": resp.status_code, "body": resp.body}
    except Exception as exc:
        raise RuntimeError(f"EZO-pH command '{cmd}' failed: {exc}") from exc

def _exec_ph_read(ctx, *, samples: int) -> float:
    if getattr(ctx, "executor", None) is not None and getattr(ctx, "mode", None) == "ui":
        last_error: str | None = None
        for attempt in range(3):
            payload = ctx.executor("ph_ezo_read", {"samples": int(samples)})
            if not isinstance(payload, dict):
                last_error = "invalid payload from executor"
                continue
            if "pH" in payload:
                signal = float(payload["pH"])
                return signal
            status = int(payload.get("status_code", 0))
            body = str(payload.get("body", "")).strip()
            last_error = f"status={status} body={body!r}"
            if status not in (254, 255):
                break
        raise RuntimeError(f"EZO-pH read failed: {last_error or 'unknown error'}")
    try:
        probe = AtlasEzoPH.from_config()
        signal = float(probe.read_ph(samples=int(samples)))
        return signal
    except Exception as exc:
        raise RuntimeError(f"EZO-pH read failed: {exc}") from exc


def _register_ph_calibration_actions() -> None:
    @huey.task()
    def ph_ezo_cmd(cmd: str, timeout_s: float = 1.5) -> dict[str, t.Any]:
        probe = AtlasEzoPH.from_config()
        resp = probe.query(cmd, timeout_s=float(timeout_s))
        return {"status_code": resp.status_code, "body": resp.body}

    @huey.task()
    def ph_ezo_read(samples: int = 3) -> dict[str, t.Any]:
        probe = AtlasEzoPH.from_config()
        signal = float(probe.read_ph(samples=int(samples)))
        return {"Voltage": signal}

    def _default_normalizer(result: t.Any) -> dict[str, t.Any]:
        return result if isinstance(result, dict) else {}

    register_calibration_action(
        "ph_ezo_cmd",
        lambda payload: (
            ph_ezo_cmd(str(payload["cmd"]), float(payload.get("timeout_s", 1.5))),
            "EZO-pH command",
            _default_normalizer,
        ),
    )
    register_calibration_action(
        "ph_ezo_read",
        lambda payload: (
            ph_ezo_read(int(payload.get("samples", 3))),
            "EZO-pH read",
            _default_normalizer,
        ),
    )

try:
    _register_ph_calibration_actions()
except Exception:
    pass


# Session steps (UI + CLI flow)
class Intro(SessionStep):
    step_id = "intro"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.info("pH calibration", "Place probe in buffer.")

    def advance(self, ctx):
        ctx.data["timeout_s"] = ctx.inputs.float("timeout_s", minimum=0.5, maximum=20.0, default=1.5)
        ctx.data["read_samples"] = ctx.inputs.int("read_samples", minimum=1, maximum=10, default=3)
        ctx.data["points"] = []
        return Clear()

class Clear(SessionStep):
    step_id = "clear"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.action("Clear existing calibration")

    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        result = _exec_ph_cmd(ctx, cmd="Cal,clear", timeout_s=timeout_s)
        return BufferMid()

class BufferMid(SessionStep):
    step_id = "buffer_7"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.action("Measure buffer pH 7.00")

    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        samples = int(ctx.data.get("read_samples", 3))
        reading = _exec_ph_read(ctx, samples=samples)
        ctx.data["points"].append({"x": 7.00, "y": float(reading)})
        return BufferLow()
    
class BufferLow(SessionStep):
    step_id = "buffer_4"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.action("Measure buffer pH 4.01")

    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        samples = int(ctx.data.get("read_samples", 3))
        reading = _exec_ph_read(ctx, samples=samples)
        ctx.data["points"].append({"x": 4.01, "y": float(reading)})
        return Finalize()
    
class Finalize (SessionStep):
    step_id = "finalize"

    def render(self, ctx) -> structs.CalibrationStep:
        step = steps.action("Finalize and save")
        if ctx.data.get("points"):
            step.metadata = {"chart": _build_chart_from_points(ctx.data["points"])}
        return step
    
    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        points: list[dict[str, float]] = list(ctx.data.get("points", []))
        xs = [float(p["x"]) for p in points]
        ys = [float(p["y"]) for p in points]        

        calibration = PHBufferCalibration(
            calibration_name="ph_calibration",
            calibrated_on_pioreactor_unit=get_unit_name(),
            created_at=current_utc_datetime(),
            curve_data_=[1.0, 0.0],
            curve_type="poly",
            x="pH",
            y="voltage",
            recorded_data={"x": [xs], "y": [ys]},
            buffer_solution="default",
        )
        link = ctx.store_calibration(calibration, "ph")
        ctx.complete({"calibration": link})
        return None

PH_STEPS: StepRegistry = {
    Intro.step_id: Intro,
    Clear.step_id: Clear,
    BufferMid.step_id: BufferMid,
    BufferLow.step_id: BufferLow,
    Finalize.step_id: Finalize,
}

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

class BufferBasedPHProtocol(CalibrationProtocol):
    target_device = "ph"
    protocol_name = "buffer_based"
    title = "pH calibration (buffer solutions)"
    description = "Calibrate the pH sensor using buffer solutions"
    step_registry = PH_STEPS

    @classmethod
    def start_session(cls, target_device: str) -> CalibrationSession:
        return start_ph_buffer_session(target_device)

    def run(self, target_device: str) -> structs.CalibrationBase | list[structs.CalibrationBase]:
        session = start_ph_buffer_session(target_device)
        calibrations = run_session_in_cli(self.step_registry, session)
        return t.cast(structs.CalibrationBase, calibrations[-1])