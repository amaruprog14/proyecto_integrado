document.addEventListener("DOMContentLoaded", () => {
    const modalElement = document.getElementById("maintainer-form-modal");
    const modalBody = document.getElementById("maintainer-form-modal-body");
    const modalTitle = document.getElementById("maintainer-form-modal-title");
    if (!modalElement || !modalBody || !modalTitle || !window.bootstrap?.Modal) return;

    const modal = window.bootstrap.Modal.getOrCreateInstance(modalElement);
    const loadingMarkup = '<div class="text-center py-5" role="status">Cargando formulario…</div>';
    let busy = false;

    const showError = (message) => {
        modalBody.innerHTML = "";
        const alert = document.createElement("div");
        alert.className = "alert alert-danger mb-0";
        alert.setAttribute("role", "alert");
        alert.textContent = message;
        modalBody.append(alert);
    };

    const parseForm = (html, actionUrl) => {
        const page = new DOMParser().parseFromString(html, "text/html");
        const form = page.querySelector("main form[method='post']");
        if (!form) return null;
        form.action = actionUrl;

        const usernameData = page.querySelector("#existing-usernames");
        return {
            form,
            title: page.querySelector("main h1")?.textContent.trim() || "Formulario",
            usernameData,
        };
    };

    const showForm = (parsed) => {
        modalTitle.textContent = parsed.title;
        modalBody.innerHTML = "";
        parsed.form.classList.remove("attention-entry-card");
        parsed.form.classList.add("maintainer-modal-form");
        parsed.form.dataset.modalForm = "true";
        modalBody.append(parsed.form);
        if (parsed.usernameData) {
            modalBody.append(parsed.usernameData);
        }
        parsed.form.querySelectorAll(".attention-entry-field .invalid-feedback").forEach((feedback, index) => {
            const field = feedback.closest(".attention-entry-field").querySelector(
                "input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea",
            );
            if (!field) return;
            feedback.id ||= `modal-field-error-${index}`;
            field.classList.add("is-invalid");
            field.setAttribute("aria-invalid", "true");
            const describedBy = new Set(
                (field.getAttribute("aria-describedby") || "").split(" ").filter(Boolean),
            );
            describedBy.add(feedback.id);
            field.setAttribute("aria-describedby", [...describedBy].join(" "));
        });
        document.dispatchEvent(
            new CustomEvent("sgr:modal-form-loaded", { detail: { form: parsed.form } }),
        );
        const invalidField = parsed.form.querySelector(".is-invalid, [aria-invalid='true']");
        invalidField?.focus();
    };

    document.addEventListener("click", async (event) => {
        const link = event.target.closest("a[data-modal-form]");
        if (!link) return;
        event.preventDefault();
        if (busy) return;
        busy = true;
        modalTitle.textContent = link.textContent.trim() || "Formulario";
        modalBody.innerHTML = loadingMarkup;
        modal.show();
        try {
            const response = await fetch(link.href, {
                headers: { "X-Modal-Request": "true" },
                credentials: "same-origin",
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const parsed = parseForm(await response.text(), response.url);
            if (!parsed) throw new Error("No se encontró el formulario solicitado.");
            showForm(parsed);
        } catch (error) {
            showError("No se pudo cargar el formulario. Cierra esta ventana e inténtalo nuevamente.");
        } finally {
            busy = false;
        }
    });

    modalBody.addEventListener("click", (event) => {
        const cancel = event.target.closest("a.attention-entry-cancel");
        if (!cancel) return;
        event.preventDefault();
        modal.hide();
    });

    modalBody.addEventListener("submit", async (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || form.dataset.modalForm !== "true") return;
        event.preventDefault();
        if (busy) return;
        busy = true;

        const submitButton = form.querySelector('button[type="submit"]');
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.dataset.originalText = submitButton.textContent.trim();
            submitButton.textContent = "Guardando…";
        }

        try {
            const response = await fetch(form.action || window.location.href, {
                method: "POST",
                body: new FormData(form),
                headers: { "X-Modal-Request": "true" },
                credentials: "same-origin",
            });
            if (response.status === 204) {
                modal.hide();
                window.location.reload();
                return;
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const parsed = parseForm(await response.text(), response.url);
            if (!parsed) throw new Error("El servidor no devolvió el formulario esperado.");
            showForm(parsed);
        } catch (error) {
            showError("No se pudo guardar el formulario. Revisa tu conexión e inténtalo nuevamente.");
        } finally {
            busy = false;
        }
    });

    modalElement.addEventListener("hidden.bs.modal", () => {
        modalBody.innerHTML = "";
    });
});
