function bindActivityItemChoices(form) {
    const item = form.querySelector("select[data-eligible-items]");
    if (!item || item.dataset.bound) return;
    item.dataset.bound = "true";
    const official = form.querySelector('select[name="official"]');
    const date = form.querySelector('input[name="date"]');
    const feedback = document.createElement("p");
    feedback.className = "attention-entry-hint";
    feedback.setAttribute("role", "status");
    item.after(feedback);
    let controller;

    async function refresh() {
        controller?.abort();
        const currentRequest = new AbortController();
        controller = currentRequest;
        if (!official.value || !date.value) {
            item.disabled = false;
            feedback.textContent = "Selecciona un funcionario y una fecha para consultar sus ítems.";
            return;
        }
        const url = new URL(item.dataset.eligibleItems, window.location.origin);
        url.searchParams.set("official", official.value);
        url.searchParams.set("date", date.value);
        if (item.dataset.activityId) url.searchParams.set("activity", item.dataset.activityId);
        const selected = item.value;
        item.disabled = true;
        feedback.textContent = "Consultando ítems disponibles…";
        try {
            const response = await fetch(url, {signal: currentRequest.signal, credentials: "same-origin"});
            if (!response.ok) throw new Error("No se pudieron consultar los ítems.");
            const {items} = await response.json();
            if (currentRequest.signal.aborted) return;
            item.replaceChildren(new Option("---------", ""), ...items.map(row => new Option(row.item_name, row.id)));
            item.value = items.some(row => String(row.id) === selected) ? selected : "";
            feedback.textContent = items.length ? "" : "No hay ítems disponibles para esta fecha y funcionario.";
        } catch (error) {
            if (error.name !== "AbortError") {
                feedback.textContent = "No se pudieron actualizar los ítems. El SGR validará la selección al guardar.";
            }
        } finally {
            if (controller === currentRequest) item.disabled = false;
        }
    }

    official.addEventListener("change", refresh);
    date.addEventListener("change", refresh);
}

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("main form[method='post']").forEach(bindActivityItemChoices);
});
document.addEventListener("sgr:modal-form-loaded", event => bindActivityItemChoices(event.detail.form));
