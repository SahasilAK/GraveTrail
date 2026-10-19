/* Keep Material's native palette persistence and first-paint handling. */
(() => {
  const title = document.querySelector('.md-header__topic:first-child .md-ellipsis');
  if (title?.textContent.trim() === "GraveTrail") {
    const trail = document.createElement("span");
    trail.className = "gt-wordmark-trail";
    trail.textContent = "Trail";
    title.replaceChildren(document.createTextNode("Grave"), trail);
  }
  const palette = document.querySelector('[data-md-component="palette"]');
  if (!palette) return;
  const inputs = Array.from(palette.querySelectorAll('input[name="__palette"]'));
  const select = document.createElement("select");
  select.className = "gt-theme-select";
  select.setAttribute("aria-label", "Color theme");
  for (const input of inputs) select.add(new Option(input.getAttribute("aria-label"), input.dataset.mdColorScheme));
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
