USE CATALOG main;
USE SCHEMA lake;

CREATE OR REFRESH STREAMING TABLE clean (
    CONSTRAINT positive EXPECT (amount > 0) ON VIOLATION DROP ROW
) AS SELECT id, raw_amount AS amount, change_time FROM STREAM(events);

CREATE OR REFRESH STREAMING TABLE current_events;
CREATE FLOW event_changes AS AUTO CDC INTO current_events
FROM STREAM(clean) KEYS (id) SEQUENCE BY change_time
COLUMNS (id, amount);
