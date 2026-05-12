# -*- coding: utf-8 -*-
from __future__ import annotations

import typing as t
import logging
from datetime import datetime

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


logger = logging.getLogger("ph_calibration")


class PhEzoCalibration(structs.CalibrationBase, kw_only=True, tag="ph_ezo"):
    """
    Stores metadata for an Atlas EZO-pH calibration event.

    Note: the EZO board performs its own calibration internally. This record is
    primarily for traceability + exportability (buffers used, timestamps, etc).
    """

    x: str = "pH"
    y: str = "pH"
    buffers_used: list[float]
    ezo_calibration_status: str
    notes: str = ""


def _new_calibration_name() -> str:
    # Keep it filename-friendly.
    return f"ezo_ph_{utc_iso_timestamp().replace(':', '').replace('-', '')}"


def _poly_identity() -> structs.PolyFitCoefficients:
    # y = 1*x + 0
    return structs.PolyFitCoefficients([1.0, 0.0])


def _build_chart_from_points(points: list[dict[str, float]]) -> dict[str, t.Any]:
    return {
        "title": "EZO-pH calibration checkpoints",
        "x_label": "Buffer pH",
        "y_label": "Measured pH",
        "series": [
            {
                "id": "ph",
                "label": "Measurements",
                "points": points,
            }
        ],
    }


def _exec_ph_cmd(ctx, *, cmd: str, timeout_s: float) -> dict[str, t.Any]:
    """
    Execute a raw EZO-pH command.

    - In **UI sessions**, delegate to the registered calibration action via
      `ctx.executor`, which runs in a worker process that has GPIO / I²C access.
    - In **CLI or non-UI contexts**, talk directly to the probe.
    """

    logger.info(
        "ph_calibration: exec_ph_cmd cmd=%s timeout_s=%.2f mode=%s",
        cmd,
        timeout_s,
        getattr(ctx, "mode", "?"),
    )

    # UI path: use the executor, which is how other calibrations work and avoids
    # the webserver process needing direct GPIO access. We also retry a couple
    # of times on transient EZO error codes (254 / 255).
    if getattr(ctx, "executor", None) is not None and getattr(ctx, "mode", None) == "ui":
        last_status = 0
        last_body: t.Any = None
        for attempt in range(3):
            payload = ctx.executor("ph_ezo_cmd", {"cmd": cmd, "timeout_s": float(timeout_s)})
            if isinstance(payload, dict):
                last_status = int(payload.get("status_code", 0))
                last_body = payload.get("body")
            logger.info(
                "ph_calibration: exec_ph_cmd (ui) attempt=%d cmd=%s status_code=%s",
                attempt + 1,
                cmd,
                last_status,
            )
            if last_status == 1:
                return {"status_code": last_status, "body": last_body}
            # 254 / 255 are EZO error / no data codes; retry a couple of times.
        return {"status_code": last_status, "body": last_body}

    # CLI / non-UI fallback: run locally.
    from atlas_ezo_ph import AtlasEzoPH

    try:
        probe = AtlasEzoPH.from_config()
        resp = probe.query(cmd, timeout_s=float(timeout_s))
        logger.info(
            "ph_calibration: exec_ph_cmd (cli) completed cmd=%s status_code=%s",
            cmd,
            getattr(resp, "status_code", "?"),
        )
        return {"status_code": resp.status_code, "body": resp.body}
    except Exception as exc:
        logger.exception("ph_calibration: exec_ph_cmd error cmd=%s", cmd)
        raise RuntimeError(f"EZO-pH command '{cmd}' failed: {exc}") from exc


def _exec_ph_read(ctx, *, samples: int) -> float:
    """
    Read pH via the EZO-pH board.

    Like _exec_ph_cmd, this logs what is happening for easier debugging.
    """

    logger.info(
        "ph_calibration: exec_ph_read samples=%d mode=%s",
        int(samples),
        getattr(ctx, "mode", "?"),
    )

    # UI path: use executor. We may receive either {"pH": ...} or an error-like
    # payload with status_code/body – retry a couple of times on 254/255.
    if getattr(ctx, "executor", None) is not None and getattr(ctx, "mode", None) == "ui":
        last_error: str | None = None
        for attempt in range(3):
            payload = ctx.executor("ph_ezo_read", {"samples": int(samples)})
            if not isinstance(payload, dict):
                last_error = "invalid payload from executor"
                logger.warning("ph_calibration: exec_ph_read (ui) attempt=%d invalid payload", attempt + 1)
                continue
            if "pH" in payload:
                ph_value = float(payload["pH"])
                logger.info(
                    "ph_calibration: exec_ph_read (ui) completed samples=%d pH=%f",
                    int(samples),
                    ph_value,
                )
                return ph_value
            status = int(payload.get("status_code", 0))
            body = str(payload.get("body", "")).strip()
            last_error = f"status={status} body={body!r}"
            logger.warning(
                "ph_calibration: exec_ph_read (ui) attempt=%d error status_code=%s body=%s",
                attempt + 1,
                status,
                body,
            )
            if status not in (254, 255):
                break
        raise RuntimeError(f"EZO-pH read failed: {last_error or 'unknown error'}")

    # CLI / non-UI path: direct hardware access.
    from atlas_ezo_ph import AtlasEzoPH

    try:
        probe = AtlasEzoPH.from_config()
        ph_value = float(probe.read_ph(samples=int(samples)))
        logger.info("ph_calibration: exec_ph_read (cli) completed samples=%d pH=%f", int(samples), ph_value)
        return ph_value
    except Exception as exc:
        logger.exception("ph_calibration: exec_ph_read error")
        raise RuntimeError(f"EZO-pH read failed: {exc}") from exc



#
# Calibration action integration (Huey executor)
#


def _register_ph_calibration_actions() -> None:
    """
    Register calibration actions that can be invoked by UI sessions via ctx.executor.

    The session executor routes actions to Huey tasks through pioreactor.web.tasks.
    """

    from pioreactor.web.config import huey
    from pioreactor.web.tasks import register_calibration_action

    from atlas_ezo_ph import AtlasEzoPH

    @huey.task()
    def ph_ezo_cmd(cmd: str, timeout_s: float = 1.5) -> dict[str, t.Any]:
        probe = AtlasEzoPH.from_config()
        resp = probe.query(cmd, timeout_s=float(timeout_s))
        return {"status_code": resp.status_code, "body": resp.body}

    @huey.task()
    def ph_ezo_read(samples: int = 3) -> dict[str, t.Any]:
        probe = AtlasEzoPH.from_config()
        ph_value = float(probe.read_ph(samples=int(samples)))
        return {"pH": ph_value}

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


# Called on import so both web + huey can see actions.
try:
    _register_ph_calibration_actions()
except Exception:
    # If imported in non-web contexts, skip registering actions.
    pass


#
# Session-based protocol
#


class Intro(SessionStep):
    step_id = "intro"

    def render(self, ctx) -> structs.CalibrationStep:
        body = "\n".join(
            [
                "This guided protocol calibrates an Atlas Scientific EZO‑pH sensor using buffer solutions.",
                "",
                "Before you start:",
                "- Stop any running pH tracking job (ph_reading) on this unit.",
                "- Prepare fresh pH 7.00 buffer and pH 4.00 buffer (optional: pH 10.00).",
                "- Rinse the probe with distilled water between buffers and gently blot dry.",
                "- Avoid bubbles on the probe tip.",
                "- In each buffer step, wait ~30 seconds for readings to stabilize before pressing Continue.",
                "",
                "Press Continue to configure the protocol.",
            ]
        )
        return steps.info("pH calibration (EZO‑pH)", body)

    def advance(self, ctx):
        logger.info("ph_calibration: Intro.advance -> Configure")
        return Configure()


class Configure(SessionStep):
    step_id = "configure"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.form(
            "Protocol settings",
            "Choose whether to run a 2‑point or 3‑point calibration.",
            [
                fields.bool("include_high_point", label="Include pH 10.00 step", default=False),
                fields.float(
                    "timeout_s",
                    label="Command timeout (seconds)",
                    minimum=0.5,
                    maximum=20.0,
                    default=1.5,
                ),
                fields.int(
                    "read_samples",
                    label="Samples per checkpoint",
                    minimum=1,
                    maximum=10,
                    default=3,
                ),
            ],
        )

    def advance(self, ctx):
        logger.info("ph_calibration: Configure.advance include_high_point=%s", ctx.inputs.bool("include_high_point", default=False))
        ctx.data["include_high_point"] = ctx.inputs.bool("include_high_point", default=False)
        ctx.data["timeout_s"] = ctx.inputs.float("timeout_s", minimum=0.5, maximum=20.0, default=1.5)
        ctx.data["read_samples"] = ctx.inputs.int("read_samples", minimum=1, maximum=10, default=3)
        ctx.data["points"] = []
        return ClearExisting()


class ClearExisting(SessionStep):
    step_id = "clear_existing"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.action(
            "Clear existing calibration",
            "\n".join(
                [
                    "This will clear any existing calibration stored on the EZO‑pH board.",
                    "Make sure you want to continue.",
                    "",
                    "Press Continue to clear calibration on the probe.",
                ]
            ),
        )

    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        logger.info("ph_calibration: ClearExisting.advance starting Cal,clear timeout_s=%.2f", timeout_s)
        result = _exec_ph_cmd(ctx, cmd="Cal,clear", timeout_s=timeout_s)
        if int(result.get("status_code", 0)) != 1:
            logger.error("ph_calibration: Cal,clear failed result=%s", result)
            raise ValueError(f"Cal,clear failed: {result}")
        logger.info("ph_calibration: ClearExisting.advance succeeded")
        return BufferMid()


class BufferMid(SessionStep):
    step_id = "buffer_7"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.action(
            "pH 7.00 buffer",
            "\n".join(
                [
                    "Place the probe in pH 7.00 buffer.",
                    "Wait until the reading stabilizes.",
                    "",
                    "Press Continue to calibrate the mid-point (7.00).",
                ]
            ),
        )

    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        samples = int(ctx.data.get("read_samples", 3))

        logger.info("ph_calibration: BufferMid.advance reading pH at 7.00 buffer")
        reading = _exec_ph_read(ctx, samples=samples)

        ctx.data["points"].append({"x": 7.00, "y": float(reading)})

        logger.info("ph_calibration: BufferMid.advance sending Cal,mid,7.00")
        result = _exec_ph_cmd(ctx, cmd="Cal,mid,7.00", timeout_s=timeout_s)
        if int(result.get("status_code", 0)) != 1:
            logger.error("ph_calibration: Cal,mid,7.00 failed result=%s", result)
            raise ValueError(f"Cal,mid,7.00 failed: {result}")
        logger.info("ph_calibration: BufferMid.advance succeeded")
        return BufferLow()


class BufferLow(SessionStep):
    step_id = "buffer_4"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.action(
            "pH 4.00 buffer",
            "\n".join(
                [
                    "Rinse the probe, then place it in pH 4.00 buffer.",
                    "Wait until the reading stabilizes.",
                    "",
                    "Press Continue to calibrate the low-point (4.00).",
                ]
            ),
        )

    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        samples = int(ctx.data.get("read_samples", 3))

        logger.info("ph_calibration: BufferLow.advance reading pH at 4.00 buffer")
        reading = _exec_ph_read(ctx, samples=samples)

        ctx.data["points"].append({"x": 4.00, "y": float(reading)})

        logger.info("ph_calibration: BufferLow.advance sending Cal,low,4.00")
        result = _exec_ph_cmd(ctx, cmd="Cal,low,4.00", timeout_s=timeout_s)
        if int(result.get("status_code", 0)) != 1:
            logger.error("ph_calibration: Cal,low,4.00 failed result=%s", result)
            raise ValueError(f"Cal,low,4.00 failed: {result}")

        if bool(ctx.data.get("include_high_point", False)):
            return BufferHigh()
        return Finalize()


class BufferHigh(SessionStep):
    step_id = "buffer_10"

    def render(self, ctx) -> structs.CalibrationStep:
        return steps.action(
            "pH 10.00 buffer (optional)",
            "\n".join(
                [
                    "Rinse the probe, then place it in pH 10.00 buffer.",
                    "Wait until the reading stabilizes.",
                    "",
                    "Press Continue to calibrate the high-point (10.00).",
                ]
            ),
        )

    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        samples = int(ctx.data.get("read_samples", 3))

        logger.info("ph_calibration: BufferHigh.advance reading pH at 10.00 buffer")
        reading = _exec_ph_read(ctx, samples=samples)

        ctx.data["points"].append({"x": 10.00, "y": float(reading)})

        logger.info("ph_calibration: BufferHigh.advance sending Cal,high,10.00")
        result = _exec_ph_cmd(ctx, cmd="Cal,high,10.00", timeout_s=timeout_s)
        if int(result.get("status_code", 0)) != 1:
            logger.error("ph_calibration: Cal,high,10.00 failed result=%s", result)
            raise ValueError(f"Cal,high,10.00 failed: {result}")
        logger.info("ph_calibration: BufferHigh.advance succeeded")
        return Finalize()


class Finalize(SessionStep):
    step_id = "finalize"

    def render(self, ctx) -> structs.CalibrationStep:
        step = steps.action(
            "Finalize and save",
            "Press Continue to verify EZO calibration status and save a calibration record to Pioreactor.",
        )
        if ctx.data.get("points"):
            step.metadata = {"chart": _build_chart_from_points(ctx.data["points"])}
        return step

    def advance(self, ctx):
        timeout_s = float(ctx.data.get("timeout_s", 1.5))
        logger.info("ph_calibration: Finalize.advance sending Cal,?")
        status_resp = _exec_ph_cmd(ctx, cmd="Cal,?", timeout_s=timeout_s)
        if int(status_resp.get("status_code", 0)) != 1:
            logger.error("ph_calibration: Cal,? failed result=%s", status_resp)
            raise ValueError(f"Cal,? failed: {status_resp}")

        status_body = str(status_resp.get("body", "")).strip()

        points: list[dict[str, float]] = list(ctx.data.get("points", []))
        xs = [float(p["x"]) for p in points]
        ys = [float(p["y"]) for p in points]

        unit = get_unit_name()
        created_at: datetime = current_utc_datetime()

        calibration = PhEzoCalibration(
            calibration_name=_new_calibration_name(),
            calibrated_on_pioreactor_unit=unit,
            created_at=created_at,
            curve_data_=_poly_identity(),
            recorded_data={"x": xs, "y": ys},
            buffers_used=xs,
            ezo_calibration_status=status_body,
            notes="Calibrated using UI protocol.",
        )

        link = ctx.store_calibration(calibration, "ph")
        ctx.complete(
            {
                "title": "pH calibration saved",
                "calibration": link,
                "ezo_status": status_body,
            }
        )
        return None


PH_STEPS: StepRegistry = {
    Intro.step_id: Intro,
    Configure.step_id: Configure,
    ClearExisting.step_id: ClearExisting,
    BufferMid.step_id: BufferMid,
    BufferLow.step_id: BufferLow,
    BufferHigh.step_id: BufferHigh,
    Finalize.step_id: Finalize,
}


def start_ph_ezo_session(target_device: str) -> CalibrationSession:
    now = utc_iso_timestamp()
    return CalibrationSession(
        session_id=_new_calibration_name(),
        protocol_name="ezo_buffer",
        target_device=target_device,
        status="in_progress",
        step_id=Intro.step_id,
        data={},
        created_at=now,
        updated_at=now,
    )


class EzoBufferPHProtocol(CalibrationProtocol[str]):
    target_device = "ph"
    protocol_name = "ezo_buffer"
    title = "Atlas EZO‑pH (buffer solutions)"
    description = "Calibrate an Atlas Scientific EZO‑pH board using pH 7.00 and pH 4.00 buffers (optional pH 10.00)."
    requirements = (
        "pH probe connected and readable",
        "pH 7.00 buffer solution",
        "pH 4.00 buffer solution",
        "Distilled water for rinsing",
        "Optional: pH 10.00 buffer solution",
    )
    priority = 50
    step_registry = PH_STEPS

    @classmethod
    def start_session(cls, target_device: str) -> CalibrationSession:
        return start_ph_ezo_session(target_device)

    def run(self, target_device: str) -> structs.CalibrationBase | list[structs.CalibrationBase]:
        # CLI run is supported via the same session steps.
        from pioreactor.calibrations.session_flow import run_session_in_cli

        session = start_ph_ezo_session(target_device)
        calibrations = run_session_in_cli(self.step_registry, session)
        if not calibrations:
            raise RuntimeError("No calibration was produced.")
        return t.cast(structs.CalibrationBase, calibrations[-1])

