// Delegación de eventos: también funciona con formularios cargados en modales.
(() => {
    const validate = (field) => {
        if (!field.matches("[data-field-pattern]")) return;
        // Python y JavaScript usan clases Unicode distintas.
        const pattern = field.dataset.fieldPattern.replaceAll("[^\\W\\d_]", "\\p{L}")
            .replaceAll("[^\\W_]", "[\\p{L}\\p{N}]")
            .replaceAll("\\w", "\\p{L}\\p{N}_");
        if (field.value === field.dataset.originalText) {
            field.setCustomValidity("");
            return;
        }
        const value = field.name === "phone" ? field.value : field.value.trim().replace(/\s+/gu, " ");
        const digits = value.replace(/[^0-9]/g, "").length;
        const invalidPhone = field.name === "phone" && value && (digits < 8 || digits > 15);
        field.setCustomValidity(invalidPhone || (value && !new RegExp(`^(?:${pattern})$`, "u").test(value))
            ? "Revisa los caracteres permitidos para este campo." : "");
    };
    document.addEventListener("input", (event) => {
        const field = event.target;
        validate(field);
        if (!field.matches("[data-member-search]")) return;
        const query = field.value.trim().toLocaleLowerCase();
        for (const option of field.closest("[data-member-picker]").querySelectorAll("[data-member-option]")) {
            option.hidden = !option.textContent.toLocaleLowerCase().includes(query);
        }
    });
    document.addEventListener("focusout", (event) => validate(event.target));
    document.addEventListener("submit", (event) => {
        event.target.querySelectorAll("[data-field-pattern]").forEach(validate);
        if (!event.target.checkValidity()) {
            event.preventDefault();
            event.stopImmediatePropagation();
            event.target.reportValidity();
        }
    }, true);
})();
