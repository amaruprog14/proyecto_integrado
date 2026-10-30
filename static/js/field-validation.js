// Delegación de eventos: también funciona con formularios cargados en modales.
(() => {
    const validate = (field) => {
        if (!field.matches("[data-field-pattern]")) return;
        // Python y JavaScript usan clases Unicode distintas.
        const pattern = field.dataset.fieldPattern.replaceAll("[^\\W\\d_]", "\\p{L}")
            .replaceAll("[^\\W_]", "[\\p{L}\\p{N}]")
            .replaceAll("\\w", "\\p{L}\\p{N}_");
        const value = field.value.trim().replace(/\s+/gu, " ");
        const digits = value.replace(/[^0-9]/g, "").length;
        const invalidPhone = field.name === "phone" && value && (digits < 8 || digits > 15);
        field.setCustomValidity(invalidPhone || (value && !new RegExp(`^(?:${pattern})$`, "u").test(value))
            ? "Revisa los caracteres permitidos para este campo." : "");
    };
    document.addEventListener("input", (event) => validate(event.target));
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
