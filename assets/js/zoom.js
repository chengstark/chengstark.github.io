// Initialize image zoom once both the document and deferred zoom library are ready.
function initializeImageZoom() {
  if (typeof mediumZoom !== "function") return;

  window.medium_zoom = mediumZoom("[data-zoomable]", {
    background: getComputedStyle(document.documentElement).getPropertyValue("--global-bg-color") + "ee",
    margin: 24,
    scrollOffset: 20,
  });

  document.querySelectorAll("[data-zoomable]").forEach((image) => {
    image.style.cursor = "zoom-in";
  });

  window.medium_zoom.on("open", (event) => {
    event.target.style.cursor = "zoom-out";
  });
  window.medium_zoom.on("closed", (event) => {
    event.target.style.cursor = "zoom-in";
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeImageZoom);
} else {
  initializeImageZoom();
}
