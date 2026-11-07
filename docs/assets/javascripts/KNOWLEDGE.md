# docs/assets/javascripts/

`themes.js` — Upgrades Material's eleven registry-generated palette radios into a named native select.
Reuses Material's persistence and first-paint palette handling; follows system updates,
stops Material's Enter-to-cycle shortcut inside the select and retains the original
toggle as a fallback if enhancement fails. Names come from native radio labels; the header wordmark colors Trail with the active link shade. Explicitly allowlisted for publication.

Moves the existing palette form after search in the header DOM so visual order and keyboard/reading order agree: Search → Color theme → repository link. Material search, palette events and persistence stay attached to their original elements.
