document.addEventListener("click", (event) => {
    const link = event.target.closest("[data-evidence-preview]");
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    const viewer = link.closest("[data-evidence-gallery]")?.querySelector("dialog");
    if (typeof viewer?.showModal !== "function") return;

    event.preventDefault();
    const filename = link.textContent.trim();
    const photo = viewer.querySelector("img");
    viewer.querySelector("h3").textContent = filename;
    photo.alt = filename;
    photo.src = link.href;
    viewer.addEventListener("close", () => photo.removeAttribute("src"), { once: true });
    viewer.showModal();
});

function connectEvidenceUpdates(status) {
    const gallerySelector = "[data-evidence-gallery]";
    const url = new URL(status.dataset.evidenceUpdates, window.location.origin);
    url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    let socket;
    let update;
    let retry;
    let delay = 1000;
    let pending = false;
    let fetching = false;
    let stopped = false;

    function rememberDraft(event) {
        const form = event.target.closest(`${gallerySelector} form[method="post"]`);
        if (form) form.dataset.evidenceDraft = "";
    }

    async function refresh() {
        const gallery = document.querySelector(gallerySelector);
        if (!pending || !gallery || fetching || stopped || gallery.querySelector("dialog[open]")) return;
        if (gallery.querySelector("[data-evidence-draft]")) {
            status.textContent = "Hay cambios en las evidencias. Tu borrador seguirá disponible hasta que lo envíes o recargues.";
            return;
        }
        fetching = true;
        pending = false;
        try {
            const response = await fetch(window.location.href, { cache: "no-store" });
            if (stopped || !gallery.isConnected) return;
            if (response.redirected || [403, 404].includes(response.status)) {
                gallery.remove();
                status.textContent = "La sesión o los permisos cambiaron. Vuelve a una sección autorizada.";
                return;
            }
            if (!response.ok) throw new Error();
            const page = new DOMParser().parseFromString(await response.text(), "text/html");
            if (stopped || !gallery.isConnected) return;
            const fresh = page.querySelector(gallerySelector);
            if (!fresh) {
                gallery.remove();
                status.textContent = "El historial de evidencias ya no está disponible.";
                return;
            }
            if (gallery.querySelector("dialog[open], [data-evidence-draft]")) {
                pending = true;
                return;
            }
            for (const section of gallery.querySelectorAll("details[data-evidence-section]")) {
                const batch = section.closest("li[id^='evidence-batch-']");
                const selector = `details[data-evidence-section="${section.dataset.evidenceSection}"]`;
                const replacement = (batch ? fresh.querySelector(`#${batch.id}`) : fresh)?.querySelector(selector);
                if (replacement) replacement.open = section.open;
            }
            if (!gallery.isEqualNode(fresh)) {
                gallery.replaceWith(document.importNode(fresh, true));
                status.textContent = "Evidencias actualizadas.";
            }
        } catch {
            status.textContent = "No se pudo actualizar el historial de evidencias.";
        } finally {
            fetching = false;
            if (pending && !gallery.querySelector("dialog[open], [data-evidence-draft]")) schedule();
        }
    }

    function schedule() {
        pending = true;
        window.clearTimeout(update);
        update = window.setTimeout(refresh, 120);
    }

    function connect() {
        socket = new WebSocket(url);
        socket.addEventListener("open", () => {
            delay = 1000;
            status.textContent = "Actualización de evidencias conectada.";
            schedule();
        });
        socket.addEventListener("message", (event) => {
            try {
                if (JSON.parse(event.data).type === "activities.changed") schedule();
            } catch { /* Solo se procesan avisos válidos. */ }
        });
        socket.addEventListener("close", (event) => {
            if (stopped) return;
            if (event.code === 4403) {
                document.querySelector(gallerySelector)?.remove();
                status.textContent = "La sesión o los permisos cambiaron. Vuelve a una sección autorizada.";
                return;
            }
            status.textContent = "Actualización de evidencias desconectada.";
            retry = window.setTimeout(connect, delay);
            delay = Math.min(delay * 2, 30000);
        });
    }

    document.addEventListener("input", rememberDraft);
    document.addEventListener("change", rememberDraft);
    document.addEventListener("close", (event) => {
        if (pending && event.target.closest(gallerySelector)) schedule();
    }, true);
    window.addEventListener("pagehide", () => {
        stopped = true;
        window.clearTimeout(retry);
        window.clearTimeout(update);
        socket?.close();
    });
    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            stopped = false;
            connect();
        }
    });
    connect();
}

const evidenceUpdateStatus = document.querySelector("[data-evidence-updates]");
if (evidenceUpdateStatus && typeof WebSocket === "function") connectEvidenceUpdates(evidenceUpdateStatus);
