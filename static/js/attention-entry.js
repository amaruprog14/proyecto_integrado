document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("#attention-entry-form");
    const attentionType = document.querySelector("#id_attention_type");
    const subattentionType = document.querySelector("#id_subattention_type");
    const submitButton = form?.querySelector('button[type="submit"]');

    if (
        !(form instanceof HTMLFormElement) ||
        !(attentionType instanceof HTMLSelectElement) ||
        !(subattentionType instanceof HTMLSelectElement) ||
        !(submitButton instanceof HTMLButtonElement)
    ) {
        return;
    }

    const updateSubattentionOptions = (clearInvalidSelection) => {
        const selectedType = attentionType.value;
        let hasOptions = false;

        [...subattentionType.options].forEach((option) => {
            const optionType = option.dataset.attentionType;
            if (!optionType) return;

            const isAvailable = optionType === selectedType;
            option.hidden = !isAvailable;
            option.disabled = !isAvailable;
            hasOptions ||= isAvailable;

            if (clearInvalidSelection && !isAvailable && option.selected) {
                subattentionType.value = "";
            }
        });

        subattentionType.disabled = !selectedType || !hasOptions;
    };

    attentionType.addEventListener("change", () => updateSubattentionOptions(true));
    form.addEventListener("submit", () => {
        submitButton.disabled = true;
        submitButton.textContent = submitButton.dataset.loadingText || "Guardando…";
    });

    updateSubattentionOptions(false);

    const origin = form.querySelector("#id_origin");
    const folio = form.querySelector("#id_client_request");
    const requestFields = form.querySelector("#attention-request-fields");
    if (!origin || !folio || !requestFields) return;

    const status = requestFields.querySelector("#attention-request-status");
    const rut = form.elements.recipient_national_id;
    const name = form.elements.recipient_full_name;
    let controller;

    const updateOrigin = (showErrors = false) => {
        const linked = origin.value === "linked";
        const showFolio = linked || (showErrors && requestFields.dataset.invalid === "true");
        requestFields.hidden = !showFolio;
        folio.disabled = !showFolio;
        folio.required = linked;
    };

    folio.addEventListener("change", async () => {
        controller?.abort();
        rut.value = "";
        name.value = "";
        status.textContent = "";
        if (!folio.value) return;

        const request = new AbortController();
        controller = request;
        const url = new URL(requestFields.dataset.url, window.location.origin);
        url.searchParams.set("folio", folio.value);
        status.textContent = "Cargando datos del solicitante…";
        try {
            const response = await fetch(url, { signal: request.signal });
            if (!response.ok || response.redirected) throw new Error();
            const item = await response.json();
            if (request.signal.aborted) return;
            rut.value = item.rut;
            name.value = item.name;
            form.elements.delegation.value = String(item.delegation_id);
            status.textContent = "Datos del solicitante cargados.";
        } catch {
            if (!request.signal.aborted) {
                status.textContent = "No se pudieron cargar los datos. Vuelve a seleccionar la solicitud o completa los campos.";
            }
        }
    });

    origin.addEventListener("change", () => {
        controller?.abort();
        status.textContent = "";
        if (origin.value === "direct") folio.value = "";
        updateOrigin();
    });
    updateOrigin(true);
});
