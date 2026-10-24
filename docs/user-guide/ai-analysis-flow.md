# AI analysis flow

Upload one SQL, SAS or dbt dataset. Static analysis is the offline default.
Select **Use AI for analysis** to preview the family, selected provider/model,
files/parts, estimated requests and input/output tokens. Configure unknown model
token limits in administration before starting. Source/network grants remain
required; preview itself makes no model calls.

Choose **Analyze with AI** once. File extraction, the bounded completion wave,
necessary saved-detail consolidation and deterministic linking run automatically.
Progress includes saved parts and current stage. Cancel preserves saved work and
the previous graph. A compatible run can resume; an unknown response requires
explicit retry acknowledgement because it may have been billed.

**AI budget overrides** offers a 10–50% maximum output share (default 30%), effective
allowances and capacity provenance. Optional Advanced exact overrides and saved
Custom limits retain clear precedence; the selected allocation is pinned for resume.
After bounded item recovery, available validated details publish with explicit
incomplete coverage. **Retry unresolved AI work** retries only those items and
reuses successful checkpoints. Incomplete initial/completion work defers later
enrichment until repair. See [controls and recovery](ai-analysis-controls-and-recovery.md).

An AI graph remains inferred and semantic completeness is not guaranteed. Processing
coverage and semantic uncertainty are separate. Explicit Static builds use the
static extractor even after an AI build. See [AI analysis](../AI_ANALYSIS.md).
