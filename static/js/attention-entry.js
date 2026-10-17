document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("#attention-entry-form");
    const attentionType = document.querySelector("#attention-type");
    const subattentionType = document.querySelector("#subattention-type");
    const registeredAt = document.querySelector("#attention-registered-at");
    const demoDialog = document.querySelector("#attention-entry-dialog");
    const closeDialog = document.querySelector("#attention-entry-dialog-close");

    if (
        !(form instanceof HTMLFormElement) ||
        !(attentionType instanceof HTMLSelectElement) ||
        !(subattentionType instanceof HTMLSelectElement) ||
        !(registeredAt instanceof HTMLElement) ||
        !(demoDialog instanceof HTMLDialogElement) ||
        !(closeDialog instanceof HTMLButtonElement)
    ) {
        return;
    }

    const updateSubattentionOptions = (clearSelection) => {
        if (clearSelection) subattentionType.value = "";
        const selectedType = attentionType.value;
        let availableOptions = 0;

        [...subattentionType.options].forEach((option) => {
            if (!option.dataset.attentionType) return;
            const isAvailable = option.dataset.attentionType === selectedType;
            option.hidden = !isAvailable;
            option.disabled = !isAvailable;
            if (isAvailable) availableOptions += 1;
        });

        subattentionType.disabled = !selectedType || availableOptions === 0;
    };

    const updateRegisteredAt = () => {
        registeredAt.textContent = new Intl.DateTimeFormat("es-CL", {
            dateStyle: "short",
            timeStyle: "short",
        }).format(new Date());
    };

    attentionType.addEventListener("change", () => updateSubattentionOptions(true));
    closeDialog.addEventListener("click", () => demoDialog.close());
    demoDialog.addEventListener("click", (event) => {
        if (event.target === demoDialog) demoDialog.close();
    });

    form.addEventListener("submit", (event) => {
        event.preventDefault();

        if (!form.reportValidity()) return;
        if (!attentionType.value || subattentionType.disabled) {
            subattentionType.setCustomValidity("Seleccione una Sub Atención asociada al tipo elegido.");
            subattentionType.reportValidity();
            subattentionType.setCustomValidity("");
            return;
        }

        if (window.Swal) {
            window.Swal.fire({
                title: "Demostración sin persistencia",
                text: "Los campos son válidos, pero esta pantalla aún no está conectada al backend. No se creó ni guardó una atención.",
                icon: "info",
                confirmButtonText: "Volver al formulario",
                confirmButtonColor: "#ad0000",
            });
        } else {
            demoDialog.showModal();
        }
    });

    updateSubattentionOptions(false);
    updateRegisteredAt();
    window.setInterval(updateRegisteredAt, 60_000);
});
