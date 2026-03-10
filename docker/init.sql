-- ─────────────────────────────────────────────────
-- Weather ETL - PostgreSQL Schema
-- ─────────────────────────────────────────────────

-- Raw weather forecasts (as received from API)
CREATE TABLE IF NOT EXISTS weather_raw (
    id              SERIAL PRIMARY KEY,
    city            VARCHAR(100) NOT NULL,
    latitude        DECIMAL(9, 6) NOT NULL,
    longitude       DECIMAL(9, 6) NOT NULL,
    fetched_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    raw_json        JSONB NOT NULL
);

-- Processed daily forecasts
CREATE TABLE IF NOT EXISTS weather_daily (
    id                  SERIAL PRIMARY KEY,
    city                VARCHAR(100) NOT NULL,
    forecast_date       DATE NOT NULL,
    temperature_max     DECIMAL(5, 2),    -- °C
    temperature_min     DECIMAL(5, 2),    -- °C
    precipitation_sum   DECIMAL(6, 2),    -- mm
    snowfall_sum        DECIMAL(6, 2),    -- cm
    wind_speed_max      DECIMAL(6, 2),    -- km/h
    wind_gusts_max      DECIMAL(6, 2),    -- km/h
    weather_code        INTEGER,          -- WMO code
    uv_index_max        DECIMAL(4, 2),
    sunrise             TIMESTAMP WITH TIME ZONE,
    sunset              TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(city, forecast_date)
);

-- Processed hourly forecasts
CREATE TABLE IF NOT EXISTS weather_hourly (
    id                  SERIAL PRIMARY KEY,
    city                VARCHAR(100) NOT NULL,
    forecast_time       TIMESTAMP WITH TIME ZONE NOT NULL,
    temperature         DECIMAL(5, 2),    -- °C
    feels_like          DECIMAL(5, 2),    -- °C
    precipitation       DECIMAL(5, 2),    -- mm
    rain                DECIMAL(5, 2),    -- mm
    snowfall            DECIMAL(5, 2),    -- cm
    wind_speed          DECIMAL(6, 2),    -- km/h
    wind_direction      INTEGER,          -- degrees
    humidity            INTEGER,          -- %
    sunshine_duration   DECIMAL(6,2),    -- seconds per hour
    weather_code        INTEGER,          -- WMO code
    is_day              BOOLEAN,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(city, forecast_time)
);

-- Weather alerts
CREATE TABLE IF NOT EXISTS weather_alerts (
    id              SERIAL PRIMARY KEY,
    city            VARCHAR(100) NOT NULL,
    alert_name      VARCHAR(100) NOT NULL,
    severity        VARCHAR(20) NOT NULL CHECK (severity IN ('info', 'warning', 'danger')),
    message         TEXT NOT NULL,
    condition_met   JSONB,                -- which values triggered the alert
    forecast_date   DATE,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at      TIMESTAMP WITH TIME ZONE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_weather_daily_city_date ON weather_daily(city, forecast_date);
CREATE INDEX IF NOT EXISTS idx_weather_hourly_city_time ON weather_hourly(city, forecast_time);
CREATE INDEX IF NOT EXISTS idx_weather_alerts_city_active ON weather_alerts(city, is_active);
CREATE INDEX IF NOT EXISTS idx_weather_alerts_created ON weather_alerts(created_at DESC);
