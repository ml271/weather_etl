-- Add soil temperature and moisture columns to weather_hourly

ALTER TABLE weather_hourly
    ADD COLUMN IF NOT EXISTS soil_temperature_0cm  DECIMAL(5, 2),
    ADD COLUMN IF NOT EXISTS soil_temperature_6cm  DECIMAL(5, 2),
    ADD COLUMN IF NOT EXISTS soil_temperature_18cm DECIMAL(5, 2),
    ADD COLUMN IF NOT EXISTS soil_moisture_0_1cm   DECIMAL(8, 6),
    ADD COLUMN IF NOT EXISTS soil_moisture_1_3cm   DECIMAL(8, 6),
    ADD COLUMN IF NOT EXISTS soil_moisture_3_9cm   DECIMAL(8, 6);
