CREATE TABLE IF NOT EXISTS ph_readings (
    experiment               TEXT NOT NULL,
    pioreactor_unit          TEXT NOT NULL,
    timestamp                TEXT NOT NULL,
    ph_reading               REAL
);

CREATE INDEX IF NOT EXISTS pH_measurements_ix ON pH_readings (experiment);
