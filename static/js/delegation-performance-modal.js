function bindDelegationPerformanceModal() {
    const Modal = window.bootstrap?.Modal;
    const status = document.getElementById("team-detail-status");
    if (!Modal || !status) return;

    function showDetail(detail, trigger) {
        const modal = Modal.getOrCreateInstance(detail);
        detail.addEventListener("hidden.bs.modal", () => {
            modal.dispose();
            detail.remove();
            trigger?.focus({preventScroll: true});
        }, {once: true});
        modal.show(trigger);
    }

    const initialDetail = document.getElementById("team-detail");
    if (initialDetail) {
        const trigger = document.getElementById(initialDetail.dataset.returnFocus);
        initialDetail.addEventListener("hidden.bs.modal", () => {
            const url = new URL(window.location.href);
            url.searchParams.delete("official");
            if (url.hash === "#team-detail" || url.hash === `#${trigger?.id}`) url.hash = "";
            window.history.replaceState(window.history.state, "", url);
        }, {once: true});
        showDetail(initialDetail, trigger);
    }

    let pending;
    document.addEventListener("click", async (event) => {
        const trigger = event.target.closest("a[data-team-detail]");
        if (!trigger || event.defaultPrevented || event.button !== 0 ||
            event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

        event.preventDefault();
        pending?.abort();
        const request = new AbortController();
        pending = request;
        const url = new URL(trigger.href);
        url.searchParams.set("fragment", "official-result");
        status.classList.add("visually-hidden");
        status.textContent = "Cargando resultado individual…";
        try {
            const response = await fetch(url, {signal: request.signal});
            if (!response.ok) throw new Error();
            const markup = await response.text();
            if (request.signal.aborted) return;
            const page = new DOMParser().parseFromString(markup, "text/html");
            const detail = page.getElementById("team-detail");
            if (!detail) throw new Error();
            status.textContent = "";
            document.body.append(detail);
            showDetail(detail, trigger);
        } catch {
            if (!request.signal.aborted) {
                status.classList.remove("visually-hidden");
                status.textContent = "No se pudo cargar el resultado individual. Intenta nuevamente.";
            }
        }
    });
}

bindDelegationPerformanceModal();
