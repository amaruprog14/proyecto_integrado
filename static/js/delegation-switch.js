// Aviso de cambios sin guardar al cambiar la delegación activa desde la cabecera.
//
// Al terminar de cargar la página (después de los demás scripts) se toma una foto de los
// formularios de edición: los POST del contenido, sin los de confirmar activar/desactivar. Un
// formulario tiene cambios pendientes si algún campo difiere de esa foto (abrirlo no cuenta, y
// volver al valor inicial tampoco) o si volvió del servidor con errores de validación, porque esos
// datos aún no se guardaron. Con cambios pendientes, «Cambiar» pide confirmación con SweetAlert2;
// si se cancela, el selector vuelve a la delegación activa y no se envía nada.
document.addEventListener("DOMContentLoaded", () => {
    const switchForm = document.querySelector("form[data-delegation-switch]");
    if (!switchForm) return;

    const SKIPPED_TYPES = ["hidden", "submit", "button", "reset"];
    const editForms = [...document.querySelectorAll("main form")].filter(
        (form) => form.method.toLowerCase() === "post" && !form.matches("[data-swal-confirm]"),
    );
    const fieldState = (form) =>
        [...form.elements]
            .filter((field) => field.name && !SKIPPED_TYPES.includes(field.type))
            .map((field) => {
                if (field.type === "checkbox" || field.type === "radio") {
                    return `${field.name}=${field.value}:${field.checked}`;
                }
                if (field instanceof HTMLSelectElement && field.multiple) {
                    return `${field.name}=${[...field.selectedOptions].map((option) => option.value).join(",")}`;
                }
                return `${field.name}=${field.value}`;
            })
            .join("\n");

    const initialState = new Map(editForms.map((form) => [form, fieldState(form)]));
    const returnedWithErrors = new Set(
        editForms.filter((form) => form.querySelector(".invalid-feedback, [role='alert']")),
    );
    const hasUnsavedChanges = () =>
        editForms.some((form) => returnedWithErrors.has(form) || fieldState(form) !== initialState.get(form));

    const select = switchForm.querySelector("select");
    const activeValue = select ? select.value : "";
    const confirmColor = () =>
        getComputedStyle(document.documentElement).getPropertyValue("--color-primary").trim() || "#ad0000";
    const message = "Hay cambios sin guardar. Si cambias de delegación se perderán. ¿Continuar?";

    const proceed = () => {
        switchForm.dataset.confirmed = "true";
        switchForm.submit();
    };
    const stay = () => {
        if (select) select.value = activeValue;
    };

    switchForm.addEventListener("submit", (event) => {
        if (switchForm.dataset.confirmed === "true" || !hasUnsavedChanges()) return;
        event.preventDefault();
        if (!window.Swal) {
            if (window.confirm(message)) proceed();
            else stay();
            return;
        }
        window.Swal.fire({
            title: "Cambios sin guardar",
            text: message,
            icon: "warning",
            showCancelButton: true,
            confirmButtonText: "Sí, cambiar de delegación",
            cancelButtonText: "Cancelar",
            confirmButtonColor: confirmColor(),
            focusCancel: true,
        }).then((result) => (result.isConfirmed ? proceed() : stay()));
    });
});
