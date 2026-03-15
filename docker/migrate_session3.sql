-- Session 3 migration: warning_templates + warnings tables

CREATE TABLE IF NOT EXISTS warning_templates (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    description TEXT,
    conditions  JSONB NOT NULL
);

INSERT INTO warning_templates (name, description, conditions) VALUES
    ('Hitzwarnung',      'Temperatur über 32°C',             '[{"parameter":"temperature_max","comparator":">","value":32,"label":"Temperatur max."}]'),
    ('Frostwarnung',     'Temperatur unter 0°C',             '[{"parameter":"temperature_min","comparator":"<","value":0,"label":"Temperatur min."}]'),
    ('Starkregen',       'Niederschlag über 20 mm',          '[{"parameter":"precipitation_sum","comparator":">","value":20,"label":"Niederschlag"}]'),
    ('Sturmwarnung',     'Windgeschwindigkeit über 60 km/h', '[{"parameter":"wind_speed_max","comparator":">","value":60,"label":"Windgeschwindigkeit"}]'),
    ('Schneefallwarnung','Schneefall über 10 cm',            '[{"parameter":"snowfall_sum","comparator":">","value":10,"label":"Schneefall"}]')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS warnings (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    station_id  INTEGER REFERENCES stations(id) ON DELETE SET NULL,
    city        VARCHAR(100) NOT NULL,
    name        VARCHAR(100) NOT NULL,
    conditions  JSONB NOT NULL,
    validity    JSONB NOT NULL,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_warnings_user_id ON warnings(user_id);
