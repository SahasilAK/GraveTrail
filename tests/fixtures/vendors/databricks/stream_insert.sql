USE CATALOG main;
USE SCHEMA lake;

CREATE TABLE target (sample_id BIGINT, soil_ph DOUBLE);

INSERT INTO target
WITH stream_rows AS (
    SELECT f.id AS id, f.soil.ph AS renamed_ph
    FROM STREAM(samples) AS f
), prepared AS (
    SELECT * FROM stream_rows
)
SELECT * FROM prepared;
