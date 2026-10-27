# docs/assets/stylesheets/

- `extra.css` — public-site semantic colors/type, header/nav/search/code/tables/forms, homepage/learning-path/example cards, installation panels and sandboxed lineage-demo layout. Base light/dark definitions cooperate with the shared palette registry injected by overrides/main.html. System fonts; responsive stacking; reduced-motion/transparency and contrast alternatives.

Hero typography separates the H1 sentence from .gt-tagline, a responsive subtitle smaller than the H1 and larger than ordinary headings/body. App styling remains in ui/style.css. No page entrance/looping animation or remote font dependency is introduced here. Keep links/focus/controls readable across configured schemes; changes require browser/responsive proof separate from static-site validation.

Header controls use consistent44px search/theme targets and deliberate gaps; repository metadata remains a quieter trailing link. Narrow layouts retain compact native search and theme controls without horizontal overflow.

Homepage .gt-guides contains direct .gt-guide-card links in a two-column grid, stacking below48em. Rounded surfaces use shared palette tokens; full-card focus/press/hover feedback respects reduced motion and increased contrast.
