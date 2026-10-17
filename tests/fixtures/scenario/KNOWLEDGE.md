# tests/fixtures/scenario/

Mixed customer/order pipeline, explicit CSV link, unresolved macro and intentional cycle. Analyze to obtain 9 assets/7 edges. Markdown is skipped by import filters.

## Subfolders
- `input/` — [input/KNOWLEDGE.md](input/KNOWLEDGE.md).

## Files
- `01_import.sas` — Deterministic sas fixture consumed by parser/workflow tests; treat as input data.
- `02_summary.sql` — Deterministic sql fixture consumed by parser/workflow tests; treat as input data.
- `03_orders.sql` — Deterministic sql fixture consumed by parser/workflow tests; treat as input data.
- `04_unresolved.sas` — Deterministic sas fixture consumed by parser/workflow tests; treat as input data.
- `05_cycle.sql` — Deterministic sql fixture consumed by parser/workflow tests; treat as input data.
- `06_consumption.sql` — Deterministic sql fixture consumed by parser/workflow tests; treat as input data.
