# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from time import sleep

try:
    import busio  # type: ignore
except Exception:  # pragma: no cover
    busio = None  # type: ignore

from pioreactor.config import config


@dataclass(frozen=True)
class EzoResponse:
    status_code: int
    body: str

    @property
    def ok(self) -> bool:
        # Atlas EZO: 1 = success, 2 = failed, 254 = pending, 255 = no data
        return self.status_code == 1


class AtlasEzoPH:
    """
    Minimal helper for Atlas Scientific EZO-pH over I2C.

    This is used by both continuous reading and calibration sessions.
    """

    DEFAULT_READ_BYTES = 31

    def __init__(self, *, i2c, address: int) -> None:
        self.i2c = i2c
        self.address = address

    @classmethod
    def from_config(cls) -> "AtlasEzoPH":
        address = int(config.get("ph_reading.config", "i2c_channel_hex"), base=16)

        if busio is None:  # pragma: no cover
            raise RuntimeError("busio is not available in this environment.")

        # In Pioreactor core plugins, SCL/SDA pins are provided by hardware helpers,
        # but for compatibility with existing deployments we fall back to (3, 2).
        try:
            from pioreactor.hardware import get_scl_pin, get_sda_pin

            scl = get_scl_pin()
            sda = get_sda_pin()
            i2c = busio.I2C(scl, sda)
        except Exception:
            i2c = busio.I2C(3, 2)

        return cls(i2c=i2c, address=address)

    def write(self, cmd: str) -> None:
        cmd_bytes = bytes(cmd + "\x00", "latin-1")  # null-terminated
        self.i2c.writeto(self.address, cmd_bytes)

    def _raw_read(self, num_bytes: int = DEFAULT_READ_BYTES) -> bytearray:
        result = bytearray(num_bytes)
        self.i2c.readfrom_into(self.address, result)
        return result

    @staticmethod
    def _strip_zeros(raw: bytearray) -> list[int]:
        return [b for b in raw if b != 0]

    @staticmethod
    def _handle_raspi_glitch(raw: list[int]) -> list[int]:
        # Atlas docs: sometimes MSB set on RasPi I2C; mask it out.
        return [b & ~0x80 for b in raw]

    def read_response(self, *, num_bytes: int = DEFAULT_READ_BYTES) -> EzoResponse:
        raw = self._raw_read(num_bytes)
        cleaned = self._strip_zeros(raw)
        if not cleaned:
            return EzoResponse(status_code=255, body="")

        status = int(cleaned[0])
        body_bytes = self._handle_raspi_glitch(cleaned[1:])
        body = "".join(chr(b) for b in body_bytes).strip()
        return EzoResponse(status_code=status, body=body)

    def query(self, cmd: str, *, timeout_s: float = 1.5) -> EzoResponse:
        self.write(cmd)
        sleep(timeout_s)
        return self.read_response()

    def read_ph(self, *, samples: int = 3, inter_sample_delay_s: float = 0.05) -> float:
        if samples < 1:
            raise ValueError("samples must be >= 1")

        values: list[float] = []
        for _ in range(samples):
            resp = self.query("R")
            if not resp.ok:
                raise RuntimeError(f"EZO-pH read failed: status={resp.status_code} body={resp.body!r}")
            values.append(float(resp.body))
            sleep(inter_sample_delay_s)

        return sum(values) / len(values)
