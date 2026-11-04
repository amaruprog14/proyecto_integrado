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
        let renderedSearch = lastSearch;

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

        const refresh = async ({ preservePage = false, force = false } = {}) => {
            window.clearTimeout(timer);
            const search = currentSearch();
            if (!force && search === lastSearch && !controller) return;
            const filtersChanged = search !== renderedSearch;
            lastSearch = search;
            const params = new URLSearchParams(search);
            if (preservePage && !filtersChanged) {
                const page = new URLSearchParams(window.location.search).get("page");
                if (page) params.set("page", page);
            }
            const url = new URL(window.location.pathname, window.location.origin);
            url.search = params.toString();

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
                if (response.status === 403 || response.status === 401 || response.redirected) {
                    document.querySelectorAll('[data-live-region]').forEach((region) => region.replaceChildren());
                    throw new Error('La sesión o los permisos cambiaron');
                }
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
                if (controller !== request || request.signal.aborted) return false;
                replacements.forEach(([region, replacement]) => region.replaceWith(document.importNode(replacement, true)));
                renderedSearch = search;
                const currentPage = page.querySelector('[data-current-page]')?.dataset.currentPage;
                if (preservePage && currentPage) url.searchParams.set("page", currentPage);
                // Actualizar opciones dependientes sin perder la selección ni el modal.
                if (document.querySelector('[data-maintainer-websocket]')) {
                    ["official", "item"].forEach((name) => {
                        const select = liveForm.querySelector(`select[name="${name}"]`);
                        const fresh = page.querySelector(`form[data-live-search] select[name="${name}"]`);
                        if (!select || !fresh) return;
                        const selected = select.value;
                        const old = select.selectedOptions[0]?.cloneNode(true);
                        select.replaceChildren(...[...fresh.options].map((option) => option.cloneNode(true)));
                        if (selected && ![...select.options].some((option) => option.value === selected) && old) select.append(old);
                        select.value = selected;
                    });
                }
                window.history.replaceState(window.history.state, "", url);
                syncExportLink();
                const count = document.querySelector('[data-live-region="footer"] .maintainer-record-count');
                showStatus(count ? count.textContent.trim() : "", { onlyForScreenReaders: true });
                return true;
            } catch (error) {
                if (error.name === "AbortError") return;
                lastSearch = null;
                showStatus(
                    "No se pudo actualizar la búsqueda. Revisa tu conexión y vuelve a intentarlo, o pulsa Buscar.",
                    { error: true },
                );
                return false;
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
            timer = window.setTimeout(() => refresh(), LIVE_SEARCH_DELAY_MS);
        });
        statusFilter?.addEventListener("change", () => {
            syncExportLink();
            refresh();
        });
        pageSizeFilter?.addEventListener("change", () => {
            syncExportLink();
            refresh();
        });
        liveForm.querySelectorAll('select[name="official"], select[name="item"], select[name="record_type"], input[type="date"]').forEach((control) => {
            control.addEventListener("change", () => { syncExportLink(); refresh(); });
        });
        document.addEventListener('sgr:maintainer-saved', () => refresh({ preservePage: true, force: true }));

        const connectionStatus = document.querySelector('[data-maintainer-websocket]');
        if (connectionStatus) {
            let socket;
            let retry = 1000;
            let retryTimer;
            let updateTimer;
            let stopped = false;
            const refreshFromSocket = async () => {
                const result = await refresh({ preservePage: true, force: true });
                if (result !== undefined && socket.readyState === WebSocket.OPEN) {
                    connectionStatus.textContent = result ? 'Actualización automática conectada.' : 'No se pudo actualizar el listado. Pulsa Buscar para intentarlo nuevamente.';
                }
            };
            const connect = () => {
                connectionStatus.textContent = 'Conectando actualización automática…';
                const url = new URL(connectionStatus.dataset.maintainerWebsocket, window.location.origin);
                url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                socket = new WebSocket(url);
                socket.addEventListener('open', () => {
                    retry = 1000;
                    refreshFromSocket();
                });
                socket.addEventListener('message', (event) => {
                    try {
                        if (!['activities.changed', 'maintainer.changed'].includes(JSON.parse(event.data).type)) return;
                    } catch { return; }
                    window.clearTimeout(updateTimer);
                    updateTimer = window.setTimeout(refreshFromSocket, 100);
                });
                socket.addEventListener('close', (event) => {
                    connectionStatus.textContent = 'Actualización automática desconectada. Los datos pueden estar desactualizados.';
                    if (event.code === 4403) {
                        document.querySelectorAll('[data-live-region]').forEach((region) => region.replaceChildren());
                        connectionStatus.textContent = 'La sesión o los permisos cambiaron. Inicia sesión o vuelve a una sección autorizada.';
                    }
                    if (stopped || event.code === 4403 || event.code === 4400) return;
                    retryTimer = window.setTimeout(connect, retry);
                    retry = Math.min(retry * 2, 30000);
                });
                socket.addEventListener('error', () => {
                    connectionStatus.textContent = 'No se pudo conectar la actualización automática.';
                });
            };
            window.addEventListener('pagehide', () => {
                stopped = true;
                window.clearTimeout(retryTimer);
                window.clearTimeout(updateTimer);
                socket?.close();
            });
            window.addEventListener('pageshow', (event) => { if (event.persisted) { stopped = false; connect(); } });
            connect();
        }
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
