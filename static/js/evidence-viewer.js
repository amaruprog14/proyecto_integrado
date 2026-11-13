const gallery = document.querySelector("[data-evidence-gallery]");
const viewer = gallery?.querySelector("dialog");

if (typeof viewer?.showModal === "function") {
    const title = viewer.querySelector("h3");
    const photo = viewer.querySelector("img");

    for (const link of gallery.querySelectorAll("[data-evidence-preview]")) {
        link.addEventListener("click", (event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

            event.preventDefault();
            const filename = link.textContent.trim();
            title.textContent = filename;
            photo.alt = filename;
            photo.src = link.href;
            viewer.showModal();
        });
    }

    viewer.addEventListener("close", () => photo.removeAttribute("src"));
}
