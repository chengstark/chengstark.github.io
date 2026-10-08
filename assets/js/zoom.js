// Initialize image zoom once both the document and deferred zoom library are ready.
function initializeImageZoom() {
  if (typeof mediumZoom !== "function") return;

  window.medium_zoom = mediumZoom("[data-zoomable]:not(.preview)", {
    background: getComputedStyle(document.documentElement).getPropertyValue("--global-bg-color") + "ee",
    margin: 24,
    scrollOffset: 20,
  });

  document.querySelectorAll("[data-zoomable]:not(.preview)").forEach((image) => {
    image.style.cursor = "zoom-in";
  });

  window.medium_zoom.on("open", (event) => {
    event.target.style.cursor = "zoom-out";
  });
  window.medium_zoom.on("closed", (event) => {
    event.target.style.cursor = "zoom-in";
  });

  const publicationImages = document.querySelectorAll(".publications .preview[data-zoomable]");
  if (publicationImages.length === 0) return;

  const lightbox = document.createElement("div");
  lightbox.className = "publication-image-lightbox";
  lightbox.setAttribute("role", "dialog");
  lightbox.setAttribute("aria-modal", "true");
  lightbox.setAttribute("aria-label", "Enlarged publication image");
  lightbox.setAttribute("aria-hidden", "true");

  const enlargedImage = document.createElement("img");
  enlargedImage.className = "publication-image-lightbox__image";

  const closeButton = document.createElement("button");
  closeButton.className = "publication-image-lightbox__close";
  closeButton.type = "button";
  closeButton.setAttribute("aria-label", "Close enlarged image");
  closeButton.textContent = "×";

  lightbox.append(enlargedImage, closeButton);
  document.body.appendChild(lightbox);

  let triggerImage = null;

  function closePublicationLightbox() {
    lightbox.classList.remove("is-open");
    lightbox.setAttribute("aria-hidden", "true");
    document.body.classList.remove("publication-lightbox-open");
    enlargedImage.removeAttribute("src");
    enlargedImage.removeAttribute("alt");
    triggerImage?.focus();
    triggerImage = null;
  }

  publicationImages.forEach((image) => {
    image.style.cursor = "zoom-in";
    image.tabIndex = 0;
    image.setAttribute("role", "button");

    const openPublicationLightbox = () => {
      triggerImage = image;
      enlargedImage.src = image.src;
      enlargedImage.alt = image.alt || "Enlarged publication image";
      lightbox.classList.add("is-open");
      lightbox.setAttribute("aria-hidden", "false");
      document.body.classList.add("publication-lightbox-open");
      closeButton.focus();
    };

    image.addEventListener("click", openPublicationLightbox);
    image.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openPublicationLightbox();
      }
    });
  });

  closeButton.addEventListener("click", closePublicationLightbox);
  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) closePublicationLightbox();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && lightbox.classList.contains("is-open")) closePublicationLightbox();
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeImageZoom);
} else {
  initializeImageZoom();
}
