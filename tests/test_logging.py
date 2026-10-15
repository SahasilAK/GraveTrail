import json
import logging

from dataforge.logging_config import JsonFormatter


def test_structured_logging_omits_unapproved_source_fields():
    record = logging.LogRecord("dataforge.test", logging.INFO, __file__, 1, "analysis_complete", (), None)
    record.run_id = "run-1"
    record.raw_content = "password=supersecret"
    obj = json.loads(JsonFormatter().format(record))
    assert obj["event"] == "analysis_complete" and obj["run_id"] == "run-1"
    assert "supersecret" not in json.dumps(obj)
