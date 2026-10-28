// Estados de carga, búsqueda en tiempo real y estados de error de los mantenedores.
//
// Carga: mientras el servidor responde, los botones con data-loading-text del formulario enviado
// se deshabilitan con un texto de espera (también evita el doble envío), y el bloque indicado en
// data-loading-target se marca como ocupado. Aplica a formularios con data-loading; los que piden
// confirmación con SweetAlert2 (maintainer-crud.js) no se marcan hasta que el envío realmente ocurre.
//
// Búsqueda en tiempo real (formulario con data-live-search): unos 400 ms después de dejar de
// escribir, o al cambiar el estado, se pide la misma página con los filtros del formulario y se
// reemplazan solo los bloques data-live-region (tabla, total y paginador), en la página 1. La URL
// se actualiza con replaceState, el enlace data-export-base siempre exporta lo escrito y la
// petición anterior se cancela. Sin JavaScript, Buscar y el envío normal siguen funcionando.
//
// Error: cada campo con un mensaje de validación queda con aria-invalid y aria-describedby, y el
// foco va al primero cuando se cierra el aviso de SweetAlert2 (o de inmediato si no hay aviso).
document.addEventListener("DOMContentLoaded", () => {
    const LIVE_SEARCH_DELAY_MS = 400;
    const busyForms = new Set();

    const setBusy = (form) => {
        form.querySelectorAll("button[data-loading-text]").forEach((button) => {
            button.dataset.idleText = button.textContent;
            button.disabled = true;
            const spinner = document.createElement("span");
            spinner.className = "spinner-border spinner-border-sm me-1";
            spinner.setAttribute("aria-hidden", "true");
            button.replaceChildren(spinner, document.createTextNode(button.dataset.loadingText));
        });
        const target = form.dataset.loadingTarget && document.querySelector(form.dataset.loadingTarget);
        if (target) {
            target.setAttribute("aria-busy", "true");
            target.classList.add("opacity-50");
        }
        busyForms.add(form);
    };

    const setIdle = (form) => {
        form.querySelectorAll("button[data-loading-text]").forEach((button) => {
            button.disabled = false;
            button.textContent = button.dataset.idleText || button.textContent;
        });
        const target = form.dataset.loadingTarget && document.querySelector(form.dataset.loadingTarget);
        if (target) {
            target.removeAttribute("aria-busy");
            target.classList.remove("opacity-50");
        }
    };

    document.querySelectorAll("form[data-loading]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!event.defaultPrevented) setBusy(form);
        });
        form.querySelectorAll("[data-swal-autosubmit]").forEach((control) => {
            control.addEventListener("change", () => {
                if (form.dataset.liveSearchReady !== "true") setBusy(form);
            });
        });
    });

    // Al volver con el botón Atrás, la página restaurada no debe quedar bloqueada.
    window.addEventListener("pageshow", (event) => {
        if (!event.persisted) return;
        busyForms.forEach(setIdle);
        busyForms.clear();
    });

    const liveForm = document.querySelector("form[data-live-search]");
    if (liveForm) {
        const searchInput = liveForm.querySelector('input[name="q"]');
        const statusFilter = liveForm.querySelector('select[name="status"]');
        const pageSizeFilter = liveForm.querySelector('select[name="page_size"]');
        const exportLink = liveForm.querySelector("a[data-export-base]");
        const liveStatus = document.querySelector("[data-live-status]");
        let controller = null;
        let timer = null;

        // Filtros del formulario sin valores vacíos ni página: un cambio de filtro vuelve a la 1.
        const currentSearch = () => {
            const params = new URLSearchParams();
            new FormData(liveForm).forEach((value, key) => {
                const text = String(value).trim();
                if (text && key !== "page") params.set(key, text);
            });
            return params.toString();
        };
        let lastSearch = currentSearch();

        const syncExportLink = () => {
            if (!exportLink) return;
            const search = currentSearch();
            const base = exportLink.dataset.exportBase;
            exportLink.href = search ? `${base}?${search}` : base;
        };

        const showStatus = (text, { error = false, onlyForScreenReaders = false } = {}) => {
            if (!liveStatus) return;
            liveStatus.textContent = text;
            liveStatus.classList.toggle("is-error", error);
            liveStatus.classList.toggle("visually-hidden", onlyForScreenReaders);
        };

        const setRegionsBusy = (busy) => {
            document.querySelectorAll("[data-live-region]").forEach((region) => {
                if (busy) region.setAttribute("aria-busy", "true");
                else region.removeAttribute("aria-busy");
                region.classList.toggle("opacity-50", busy);
            });
        };

        const refresh = async () => {
            window.clearTimeout(timer);
            const search = currentSearch();
            if (search === lastSearch && !controller) return;
            lastSearch = search;
            const url = `${window.location.pathname}${search ? `?${search}` : ""}`;

            controller?.abort();
            const request = new AbortController();
            controller = request;
            setRegionsBusy(true);
            showStatus("Buscando…");
            try {
                const response = await fetch(url, {
                    headers: { "X-Live-Search": "1" },
                    credentials: "same-origin",
                    signal: request.signal,
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const page = new DOMParser().parseFromString(await response.text(), "text/html");
                const replacements = [...document.querySelectorAll("[data-live-region]")].map((region) => [
                    region,
                    page.querySelector(`[data-live-region="${region.dataset.liveRegion}"]`),
                ]);
                // Sin los bloques esperados (p. ej., la sesión venció y llegó el login) se informa error.
                if (!replacements.length || replacements.some(([, replacement]) => !replacement)) {
                    throw new Error("Respuesta sin el listado");
                }
                replacements.forEach(([region, replacement]) => region.replaceWith(document.importNode(replacement, true)));
                window.history.replaceState(window.history.state, "", url);
                syncExportLink();
                const count = document.querySelector('[data-live-region="footer"] .maintainer-record-count');
                showStatus(count ? count.textContent.trim() : "", { onlyForScreenReaders: true });
            } catch (error) {
                if (error.name === "AbortError") return;
                lastSearch = null;
                showStatus(
                    "No se pudo actualizar la búsqueda. Revisa tu conexión y vuelve a intentarlo, o pulsa Buscar.",
                    { error: true },
                );
            } finally {
                if (controller === request) {
                    setRegionsBusy(false);
                    controller = null;
                }
            }
        };

        searchInput?.addEventListener("input", () => {
            syncExportLink();
            window.clearTimeout(timer);
            timer = window.setTimeout(refresh, LIVE_SEARCH_DELAY_MS);
        });
        statusFilter?.addEventListener("change", () => {
            syncExportLink();
            refresh();
        });
        pageSizeFilter?.addEventListener("change", () => {
            syncExportLink();
            refresh();
        });
        exportLink?.addEventListener("click", syncExportLink);
        // Buscar o Enter: envío normal del formulario (recarga completa), sin peticiones pendientes.
        liveForm.addEventListener("submit", () => {
            window.clearTimeout(timer);
            controller?.abort();
            controller = null;
        });
        liveForm.dataset.liveSearchReady = "true";
    }

    const invalidFields = [];
    document.querySelectorAll(".attention-entry-field .invalid-feedback").forEach((feedback, index) => {
        const field = feedback
            .closest(".attention-entry-field")
            .querySelector("input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea");
        if (!field) return;
        feedback.id ||= `field-error-${index}`;
        field.setAttribute("aria-invalid", "true");
        field.classList.add("is-invalid");
        const describedBy = new Set((field.getAttribute("aria-describedby") || "").split(" ").filter(Boolean));
        describedBy.add(feedback.id);
        field.setAttribute("aria-describedby", [...describedBy].join(" "));
        if (!invalidFields.includes(field)) invalidFields.push(field);
    });
    if (!invalidFields.length) return;

    const focusFirstError = () => invalidFields[0].focus();
    if (document.querySelector("[data-sgr-messages]") && window.Swal) {
        document.addEventListener("sgr:messages-closed", focusFirstError, { once: true });
    } else {
        focusFirstError();
    }
});
