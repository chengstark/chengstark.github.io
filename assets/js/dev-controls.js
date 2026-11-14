(() => {
  const storageKey = "chengstark-dev-settings";
  const root = document.documentElement;
  let enabled = false;
  let showMouseArrow = false;

  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    enabled = saved && saved.enabled === true;
    showMouseArrow = saved && saved.showMouseArrow === true;
  } catch (error) {
    // Controls still work when browser storage is unavailable.
  }

  const applyCursor = () => {
    root.classList.toggle("dev-cursor-hidden", enabled && !showMouseArrow);
  };

  // Apply the saved choice before the page is displayed.
  applyCursor();

  const initialize = () => {
    const modeToggle = document.getElementById("dev-mode-toggle");
    const cursorToggle = document.getElementById("dev-cursor-toggle");
    const options = document.getElementById("dev-options");
    const menu = document.getElementById("dev-settings-menu");
    if (!modeToggle || !cursorToggle || !options || !menu) return;

    const update = () => {
      modeToggle.checked = enabled;
      cursorToggle.checked = showMouseArrow;
      cursorToggle.disabled = !enabled;
      options.hidden = !enabled;
      applyCursor();
    };

    const save = () => {
      try {
        localStorage.setItem(storageKey, JSON.stringify({ enabled, showMouseArrow }));
      } catch (error) {
        // Keep the current choice for this page even if persistence is blocked.
      }
      update();
    };

    modeToggle.addEventListener("change", () => {
      enabled = modeToggle.checked;
      save();
    });

    cursorToggle.addEventListener("change", () => {
      showMouseArrow = cursorToggle.checked;
      save();
    });

    // Keep the dropdown open while its switches are being adjusted.
    menu.addEventListener("click", (event) => event.stopPropagation());
    update();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
