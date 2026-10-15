# Prompt repository

Version 1 task prompts share a strict GroundedResponse schema and counterexamples. Never interpolate source into the system message. User context is a JSON value. `assist` records the SHA-256 of system and template, validates exact quotes and ranges, known assets, explicit reads/writes, and quarantines unsupported claims. Full interactions are opt-in. Change prompt version and regression tests together.
