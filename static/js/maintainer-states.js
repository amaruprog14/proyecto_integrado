// Estado de carga de los mantenedores de Roles e Ítems.
//
// Mientras el servidor responde, los botones con data-loading-text del formulario enviado se
// deshabilitan con un texto de espera, y el bloque indicado en data-loading-target se marca
// como ocupado. Aplica a formularios con data-loading; los que piden confirmación con
// SweetAlert2 (maintainer-crud.js) no se marcan hasta que el envío realmente ocurre.
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
});
