function bindActivityItemChoices(form) {
    const item = form.querySelector("select[data-eligible-items]");
    if (!item || item.dataset.bound) return;
    item.dataset.bound = "true";
    const official = form.querySelector('select[name="official"]');
    const date = form.querySelector('input[name="date"]');
    const delegation = form.querySelector("select[data-activity-delegation]");
    const classificationFields = [...form.querySelectorAll("select[data-activity-classification]")];
    const parentKeys = ["area_id", "activity_type_id", "service_type_id", "attention_type_id"];
    let classification = null;

    function refreshClassification(start = 0) {
        if (!classification) return;
        for (let index = start; index < classificationFields.length; index++) {
            const field = classificationFields[index];
            const rows = classification[field.dataset.activityClassification] || [];
            const parent = classificationFields[index - 1]?.value;
            const options = index === 0 ? rows : rows.filter(row => String(row[parentKeys[index]]) === parent);
            const selected = field.value;
            field.replaceChildren(new Option("Selecciona una opción", ""), ...options.map(row => new Option(row.name, row.id)));
            field.value = options.some(row => String(row.id) === selected) ? selected : "";
            field.required = index > 0 && options.length > 0 || index === 0 && field.dataset.initialRequired === "true";
        }
    }

    classificationFields.forEach((field, index) => {
        field.dataset.initialRequired = String(field.required);
        field.addEventListener("change", () => refreshClassification(index + 1));
    });
    const feedback = document.createElement("p");
    feedback.className = "attention-entry-hint";
    feedback.setAttribute("role", "status");
    item.after(feedback);
    let controller;

    async function refresh() {
        controller?.abort();
        const currentRequest = new AbortController();
        controller = currentRequest;
        if (!official.value) {
            item.disabled = false;
            if (delegation && !delegation.disabled) {
                delegation.replaceChildren(new Option("Selecciona una opción", ""));
            }
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
            const {items, classification: catalog, delegations} = await response.json();
            if (currentRequest.signal.aborted) return;
            item.replaceChildren(new Option("---------", ""), ...items.map(row => new Option(row.item_name, row.id)));
            item.value = items.some(row => String(row.id) === selected) ? selected : "";
            if (delegation && !delegation.disabled) {
                const previous = delegation.value;
                delegation.replaceChildren(new Option("Selecciona una opción", ""),
                    ...delegations.map(row => new Option(row.delegation_name, row.id)));
                delegation.value = delegations.some(row => String(row.id) === previous) ? previous
                    : delegations.length === 1 ? String(delegations[0].id) : "";
            }
            classification = catalog;
            refreshClassification();
            feedback.textContent = items.length ? "" : date.value
                ? "No hay ítems disponibles para esta fecha y funcionario."
                : "Selecciona una fecha para consultar los ítems.";
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
    if (official.value && classificationFields.length) refresh();
}

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("main form[method='post']").forEach(bindActivityItemChoices);
});
document.addEventListener("sgr:modal-form-loaded", event => bindActivityItemChoices(event.detail.form));
