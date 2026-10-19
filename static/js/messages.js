// Muestra los mensajes de Django con SweetAlert2. Si la librería no carga, quedan visibles
// las alertas de Bootstrap que genera base.html.
document.addEventListener("DOMContentLoaded", () => {
    const container = document.querySelector("[data-sgr-messages]");
    if (!(container instanceof HTMLElement) || !window.Swal) return;

    const icons = { success: "success", danger: "error", warning: "warning", info: "info" };
    const titles = {
        success: "Operación exitosa",
        danger: "No se pudo completar",
        warning: "Atención",
        info: "Información",
    };
    const confirmButtonColor =
        getComputedStyle(document.documentElement).getPropertyValue("--color-primary").trim() || "#ad0000";

    const alerts = [...container.querySelectorAll("[data-sgr-message]")].map((item) => {
        const level = item.dataset.level;
        return {
            icon: icons[level] || "info",
            title: titles[level] || titles.info,
            text: item.textContent.trim(),
        };
    });

    container.hidden = true;
    alerts
        .reduce(
            (previous, options) =>
                previous.then(() =>
                    window.Swal.fire({ ...options, confirmButtonText: "Entendido", confirmButtonColor }),
                ),
            Promise.resolve(),
        )
        // Permite devolver el foco al primer campo con error (maintainer-states.js).
        .then(() => document.dispatchEvent(new Event("sgr:messages-closed")));
});
