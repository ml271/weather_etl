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
    sunshine_duration   DECIMAL(6,2),     -- seconds per hour
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

-- Stations (searchable city/location registry)
CREATE TABLE IF NOT EXISTS stations (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(100) NOT NULL,
    region  VARCHAR(100),               -- Bundesland / state
    country VARCHAR(50) DEFAULT 'Germany',
    lat     DECIMAL(9, 6) NOT NULL,
    lon     DECIMAL(9, 6) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stations_name   ON stations USING gin(to_tsvector('german', name));
CREATE INDEX IF NOT EXISTS idx_stations_region ON stations USING gin(to_tsvector('german', coalesce(region, '')));

-- Seed: Deutsche Städte
INSERT INTO stations (name, region, country, lat, lon) VALUES
    ('Berlin',          'Berlin',              'Germany',  52.520008,  13.404954),
    ('Hamburg',         'Hamburg',             'Germany',  53.551086,   9.993682),
    ('München',         'Bayern',              'Germany',  48.135125,  11.581981),
    ('Köln',            'Nordrhein-Westfalen', 'Germany',  50.938361,   6.959974),
    ('Frankfurt',       'Hessen',              'Germany',  50.110922,   8.682127),
    ('Stuttgart',       'Baden-Württemberg',   'Germany',  48.775846,   9.182932),
    ('Düsseldorf',      'Nordrhein-Westfalen', 'Germany',  51.225402,   6.776314),
    ('Leipzig',         'Sachsen',             'Germany',  51.339695,  12.373075),
    ('Dortmund',        'Nordrhein-Westfalen', 'Germany',  51.513587,   7.465298),
    ('Essen',           'Nordrhein-Westfalen', 'Germany',  51.455643,   7.011555),
    ('Bremen',          'Bremen',              'Germany',  53.079296,   8.801694),
    ('Dresden',         'Sachsen',             'Germany',  51.050407,  13.737262),
    ('Hannover',        'Niedersachsen',       'Germany',  52.374478,   9.738553),
    ('Nürnberg',        'Bayern',              'Germany',  49.452103,  11.076665),
    ('Duisburg',        'Nordrhein-Westfalen', 'Germany',  51.434407,   6.762329),
    ('Bochum',          'Nordrhein-Westfalen', 'Germany',  51.481845,   7.216236),
    ('Wuppertal',       'Nordrhein-Westfalen', 'Germany',  51.256213,   7.150764),
    ('Bielefeld',       'Nordrhein-Westfalen', 'Germany',  52.021580,   8.532471),
    ('Bonn',            'Nordrhein-Westfalen', 'Germany',  50.733992,   7.099674),
    ('Münster',         'Nordrhein-Westfalen', 'Germany',  51.960665,   7.626135),
    ('Karlsruhe',       'Baden-Württemberg',   'Germany',  49.006890,   8.403653),
    ('Mannheim',        'Baden-Württemberg',   'Germany',  49.487459,   8.466039),
    ('Augsburg',        'Bayern',              'Germany',  48.370545,  10.897790),
    ('Wiesbaden',       'Hessen',              'Germany',  50.082989,   8.240330),
    ('Gelsenkirchen',   'Nordrhein-Westfalen', 'Germany',  51.517744,   7.085717),
    ('Mönchengladbach', 'Nordrhein-Westfalen', 'Germany',  51.195804,   6.435734),
    ('Braunschweig',    'Niedersachsen',       'Germany',  52.269458,  10.520700),
    ('Kiel',            'Schleswig-Holstein',  'Germany',  54.323293,  10.122765),
    ('Chemnitz',        'Sachsen',             'Germany',  50.827845,  12.921370),
    ('Aachen',          'Nordrhein-Westfalen', 'Germany',  50.775346,   6.083887),
    ('Halle',           'Sachsen-Anhalt',      'Germany',  51.482845,  11.969117),
    ('Magdeburg',       'Sachsen-Anhalt',      'Germany',  52.120533,  11.627624),
    ('Freiburg',        'Baden-Württemberg',   'Germany',  47.997791,   7.842609),
    ('Krefeld',         'Nordrhein-Westfalen', 'Germany',  51.338268,   6.585101),
    ('Lübeck',          'Schleswig-Holstein',  'Germany',  53.869543,  10.686226),
    ('Oberhausen',      'Nordrhein-Westfalen', 'Germany',  51.469618,   6.851098),
    ('Erfurt',          'Thüringen',           'Germany',  50.978056,  11.029167),
    ('Mainz',           'Rheinland-Pfalz',     'Germany',  49.992863,   8.247253),
    ('Rostock',         'Mecklenburg-Vorpommern','Germany',54.092440,  12.099147),
    ('Kassel',          'Hessen',              'Germany',  51.312801,   9.479750),
    ('Hagen',           'Nordrhein-Westfalen', 'Germany',  51.360370,   7.474600),
    ('Potsdam',         'Brandenburg',         'Germany',  52.390569,  13.064473),
    ('Saarbrücken',     'Saarland',            'Germany',  49.234362,   6.996933),
    ('Hamm',            'Nordrhein-Westfalen', 'Germany',  51.680471,   7.823350),
    ('Ludwigshafen',    'Rheinland-Pfalz',     'Germany',  49.477460,   8.445492),
    ('Oldenburg',       'Niedersachsen',       'Germany',  53.143891,   8.214953),
    ('Osnabrück',       'Niedersachsen',       'Germany',  52.279186,   8.047185),
    ('Heidelberg',      'Baden-Württemberg',   'Germany',  49.398750,   8.672434),
    ('Darmstadt',       'Hessen',              'Germany',  49.872775,   8.651177),
    ('Regensburg',      'Bayern',              'Germany',  49.013432,  12.101624),
    ('Ingolstadt',      'Bayern',              'Germany',  48.763420,  11.425166),
    ('Würzburg',        'Bayern',              'Germany',  49.791304,   9.953355),
    ('Ulm',             'Baden-Württemberg',   'Germany',  48.401082,   9.987608),
    ('Fürth',           'Bayern',              'Germany',  49.477037,  10.988564),
    ('Wolfsburg',       'Niedersachsen',       'Germany',  52.422870,  10.787470),
    ('Göttingen',       'Niedersachsen',       'Germany',  51.536780,   9.932730),
    ('Recklinghausen',  'Nordrhein-Westfalen', 'Germany',  51.613770,   7.197570),
    ('Koblenz',         'Rheinland-Pfalz',     'Germany',  50.356943,   7.587768),
    ('Trier',           'Rheinland-Pfalz',     'Germany',  49.749992,   6.637143),
    ('Constance',       'Baden-Württemberg',   'Germany',  47.660500,   9.175310),
    ('Konstanz',        'Baden-Württemberg',   'Germany',  47.660500,   9.175310),
    ('Passau',          'Bayern',              'Germany',  48.574040,  13.456370),
    ('Bamberg',         'Bayern',              'Germany',  49.899929,  10.900042),
    ('Bayreuth',        'Bayern',              'Germany',  49.940868,  11.578020),
    ('Garmisch-Partenkirchen', 'Bayern',       'Germany',  47.491750,  11.095530),
    ('Berchtesgaden',   'Bayern',              'Germany',  47.631080,  13.000880),
    ('Zugspitze',       'Bayern',              'Germany',  47.421280,  10.985250),
    ('Bregenz',         'Vorarlberg',          'Austria',  47.503670,   9.747200),
    ('Wien',            'Wien',                'Austria',  48.208174,  16.373819),
    ('Graz',            'Steiermark',          'Austria',  47.070714,  15.439504),
    ('Innsbruck',       'Tirol',               'Austria',  47.269212,  11.404102),
    ('Salzburg',        'Salzburg',            'Austria',  47.809490,  13.055010),
    ('Zürich',          'Zürich',              'Switzerland', 47.376888,  8.541694),
    ('Basel',           'Basel-Stadt',         'Switzerland', 47.559601,  7.588576),
    ('Bern',            'Bern',                'Switzerland', 46.947922,  7.444608),
    ('Genf',            'Genf',                'Switzerland', 46.204391,  6.143158),
    ('Lausanne',        'Waadt',               'Switzerland', 46.519654,  6.632273)
ON CONFLICT DO NOTHING;

-- Users (auth)
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    username        VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_weather_daily_city_date ON weather_daily(city, forecast_date);
CREATE INDEX IF NOT EXISTS idx_weather_hourly_city_time ON weather_hourly(city, forecast_time);
CREATE INDEX IF NOT EXISTS idx_weather_alerts_city_active ON weather_alerts(city, is_active);
CREATE INDEX IF NOT EXISTS idx_weather_alerts_created ON weather_alerts(created_at DESC);
