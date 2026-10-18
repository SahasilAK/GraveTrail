/* Keep Material's native palette persistence and first-paint handling. */
(() => {
  const palette = document.querySelector('[data-md-component="palette"]');
  if (!palette) return;
  const names = { default: "Porcelain · light", celadon: "Celadon · light",
    slate: "Ink · dark", aubergine: "Aubergine · dark" };
  const inputs = Array.from(palette.querySelectorAll('input[name="__palette"]'));
  const select = document.createElement("select");
  select.className = "gt-theme-select";
  select.setAttribute("aria-label", "Color theme");
  for (const [scheme, name] of Object.entries(names)) select.add(new Option(name, scheme));
  const sync = () => { select.value = document.body.dataset.mdColorScheme; };
  sync();
  select.addEventListener("change", () => {
    inputs.find(input => input.dataset.mdColorScheme === select.value)?.click();
  });
  // Material's Enter-to-cycle shortcut must not intercept the native select.
  select.addEventListener("keydown", event => event.stopPropagation());
  palette.addEventListener("submit", event => event.preventDefault());
  palette.addEventListener("change", event => {
    if (inputs.includes(event.target)) select.value = event.target.dataset.mdColorScheme;
  });
  palette.append(select);
  palette.classList.add("gt-theme-picker");
  inputs.forEach(input => { input.tabIndex = -1; input.setAttribute("aria-hidden", "true"); });
  // Also follow an automatic system appearance change, without another preference store.
  new MutationObserver(sync).observe(document.body, { attributes: true,
    attributeFilter: ["data-md-color-scheme"] });
})();
