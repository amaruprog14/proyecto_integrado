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
});
