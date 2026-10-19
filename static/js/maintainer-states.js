// Estados de carga y de error de los mantenedores.
//
// Carga: mientras el servidor responde, los botones con data-loading-text del formulario enviado
// se deshabilitan con un texto de espera (también evita el doble envío), y el bloque indicado en
// data-loading-target se marca como ocupado. Aplica a formularios con data-loading; los que piden
// confirmación con SweetAlert2 (maintainer-crud.js) no se marcan hasta que el envío realmente ocurre.
//
// Error: cada campo con un mensaje de validación queda con aria-invalid y aria-describedby, y el
// foco va al primero cuando se cierra el aviso de SweetAlert2 (o de inmediato si no hay aviso).
document.addEventListener("DOMContentLoaded", () => {
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
            control.addEventListener("change", () => setBusy(form));
        });
    });

    // Al volver con el botón Atrás, la página restaurada no debe quedar bloqueada.
    window.addEventListener("pageshow", (event) => {
        if (!event.persisted) return;
        busyForms.forEach(setIdle);
        busyForms.clear();
    });

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
