INSERT INTO audit.cycle_a SELECT id FROM audit.cycle_b;
INSERT INTO audit.cycle_b SELECT id FROM audit.cycle_a;
