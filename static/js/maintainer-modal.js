document.addEventListener("DOMContentLoaded", () => {
    const modalElement = document.getElementById("maintainer-form-modal");
    const modalBody = document.getElementById("maintainer-form-modal-body");
    const modalTitle = document.getElementById("maintainer-form-modal-title");
    if (!modalElement || !modalBody || !modalTitle || !window.bootstrap?.Modal) return;

    const modal = window.bootstrap.Modal.getOrCreateInstance(modalElement);
    const loadingMarkup = '<div class="text-center py-5" role="status">Cargando formulario…</div>';
    let busy = false;
    let editConflict;

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

        return {
            form,
            title: page.querySelector("main h1")?.textContent.trim() || "Formulario",
        };
    };

    const showForm = (parsed) => {
        modalTitle.textContent = parsed.title;
        modalBody.replaceChildren(parsed.form);
        if (parsed.form.dataset.modalForm === "true") return;
        parsed.form.classList.remove("attention-entry-card");
        parsed.form.classList.add("maintainer-modal-form");
        parsed.form.dataset.modalForm = "true";
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

    const showEditConflict = (form) => {
        editConflict?.panel.remove();
        const draft = {form, title: modalTitle.textContent};
        const panel = document.createElement("div");
        panel.className = "alert alert-warning";
        const message = document.createElement("p");
        message.className = "mb-2";
        message.setAttribute("role", "status");
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "btn btn-outline-secondary btn-sm";
        panel.append(message, toggle);
        modalBody.prepend(panel);
        let current;
        let showingDraft = true;
        editConflict = {
            panel,
            retainCurrent(parsed) {
                current = parsed;
                modalBody.prepend(panel);
            },
        };

        const updatePanel = () => {
            message.textContent = showingDraft
                ? "Este registro cambió mientras lo editabas. Puedes copiar tus cambios o revisar la versión actual."
                : "Estás editando la versión actual. Tu borrador sigue disponible para consultar.";
            toggle.textContent = showingDraft ? "Ver versión actual" : "Volver a mi borrador";
        };
        updatePanel();
        toggle.focus();

        toggle.addEventListener("click", async () => {
            if (busy) return;
            if (!current) {
                busy = true;
                toggle.disabled = true;
                try {
                    const response = await fetch(form.action, {
                        headers: {"X-Modal-Request": "true"},
                        credentials: "same-origin",
                    });
                    if (!response.ok) throw new Error();
                    const parsed = parseForm(await response.text(), response.url);
                    if (!parsed?.form.elements.namedItem("edit_revision")) throw new Error();
                    current = parsed;
                } catch {
                    message.textContent = "No se pudo cargar la versión actual. Tu borrador sigue disponible.";
                    return;
                } finally {
                    busy = false;
                    toggle.disabled = false;
                }
            }
            if (!panel.isConnected) return;
            showingDraft = !showingDraft;
            showForm(showingDraft ? draft : current);
            modalBody.prepend(panel);
            updatePanel();
            toggle.focus();
        });
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
            if (response.status === 423) {
                showError(await response.text());
                return;
            }
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
        let conflicted = false;
        let lockedMessage;
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.dataset.originalText = submitButton.textContent.trim();
            submitButton.textContent = "Guardando…";
        }

        try {
            const headers = { "X-Modal-Request": "true" };
            const inlineFeedback = typeof window.Swal?.fire === "function"
                && document.querySelector('form[data-live-search-ready="true"]') !== null;
            if (inlineFeedback) headers["X-Modal-Feedback"] = "inline";
            const response = await fetch(form.action || window.location.href, {
                method: "POST",
                body: new FormData(form),
                headers,
                credentials: "same-origin",
            });
            if (response.status === 423) {
                conflicted = true;
                lockedMessage = await response.text();
                throw new Error(lockedMessage);
            }
            if (response.status === 409 && (await response.json()).code === "edit_conflict") {
                conflicted = true;
                if (modalBody.contains(form)) {
                    showEditConflict(form);
                }
                return;
            }
            if (response.status === 204) {
                modal.hide();
                if (inlineFeedback) {
                    document.dispatchEvent(new CustomEvent('sgr:maintainer-saved'));
                    window.Swal.fire({ icon: 'success', title: 'Registro guardado correctamente.', timer: 1800, showConfirmButton: false });
                    return;
                }
                window.location.reload();
                return;
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const parsed = parseForm(await response.text(), response.url);
            if (!parsed) throw new Error("El servidor no devolvió el formulario esperado.");
            if (!modalBody.contains(form)) return;
            showForm(parsed);
            editConflict?.retainCurrent(parsed);
        } catch (error) {
            if (modalBody.contains(form)) {
                modalBody.querySelector("[data-modal-save-error]")?.remove();
                const alert = document.createElement("p");
                alert.className = "alert alert-danger";
                alert.dataset.modalSaveError = "";
                alert.setAttribute("role", "alert");
                alert.textContent = lockedMessage || "No se pudo guardar el formulario. Tus cambios siguen disponibles.";
                modalBody.prepend(alert);
            }
        } finally {
            if (submitButton) {
                submitButton.textContent = submitButton.dataset.originalText;
                submitButton.disabled = conflicted;
            }
            busy = false;
        }
    });

    modalElement.addEventListener("hidden.bs.modal", () => {
        modalBody.innerHTML = "";
        editConflict = undefined;
    });
});
