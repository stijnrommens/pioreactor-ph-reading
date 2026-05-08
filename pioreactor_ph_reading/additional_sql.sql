CREATE TABLE IF NOT EXISTS ph_readings (
    experiment               TEXT NOT NULL,
    pioreactor_unit          TEXT NOT NULL,
    timestamp                TEXT NOT NULL,
    ph_reading               REAL
);