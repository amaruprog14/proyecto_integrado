// Validación en el navegador del login, la recuperación y el cambio de contraseña. Los formularios
// válidos se envían al servidor, que vuelve a validar todo.
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-password-toggle]").forEach((toggle) => {
        toggle.addEventListener("click", () => {
            const input = document.getElementById(toggle.dataset.passwordToggle);
            if (!(input instanceof HTMLInputElement)) return;

            const showPassword = input.type === "password";
            input.type = showPassword ? "text" : "password";
            toggle.textContent = showPassword ? "Ocultar" : "Mostrar";
            toggle.setAttribute("aria-pressed", String(showPassword));
            toggle.setAttribute(
                "aria-label",
                `${showPassword ? "Ocultar" : "Mostrar"} ${input.id.includes("confirm") ? "confirmación de contraseña" : "contraseña"}`,
            );
        });
    });

    // Evita el doble envío mientras el servidor responde.
    const disableSubmit = (form) => {
        form.querySelectorAll("button[type='submit']").forEach((button) => {
            button.disabled = true;
        });
    };

    const requestForm = document.querySelector("#recovery-request-form");
    if (requestForm instanceof HTMLFormElement) {
        const emailInput = document.querySelector("#recovery-email");
        const emailError = document.querySelector("#recovery-email-error");

        requestForm.addEventListener("submit", (event) => {
            if (!(emailInput instanceof HTMLInputElement) || !(emailError instanceof HTMLElement)) return;

            if (!emailInput.validity.valid || !emailInput.value.trim()) {
                event.preventDefault();
                emailError.textContent = "Ingresa un correo electrónico válido para continuar.";
                emailError.hidden = false;
                emailInput.setAttribute("aria-invalid", "true");
                emailInput.focus();
                return;
            }

            emailError.hidden = true;
            emailInput.removeAttribute("aria-invalid");
            disableSubmit(requestForm);
        });
    }

    // Nueva contraseña: recuperación por enlace y cambio con la sesión iniciada.
    const passwordForm = document.querySelector("#recovery-password-form, #password-change-form");
    if (passwordForm instanceof HTMLFormElement) {
        const passwordInput = document.querySelector("#new-password");
        const confirmationInput = document.querySelector("#confirm-password");
        const error = document.querySelector("#recovery-password-error");
        const requirements = {
            length: (value) => value.length >= 8,
            uppercase: (value) => /\p{Lu}/u.test(value),
            lowercase: (value) => /\p{Ll}/u.test(value),
            number: (value) => /[0-9]/.test(value),
            match: (value) => value.length > 0 && value === confirmationInput.value,
        };

        const updateRequirements = () => {
            if (!(passwordInput instanceof HTMLInputElement) || !(confirmationInput instanceof HTMLInputElement)) {
                return false;
            }

            let valid = true;
            Object.entries(requirements).forEach(([name, check]) => {
                const item = document.querySelector(`[data-password-requirement="${name}"]`);
                const requirementMet = check(passwordInput.value);
                if (item instanceof HTMLElement) item.classList.toggle("is-valid", requirementMet);
                valid = valid && requirementMet;
            });
            return valid;
        };

        passwordInput?.addEventListener("input", updateRequirements);
        confirmationInput?.addEventListener("input", updateRequirements);

        passwordForm.addEventListener("submit", (event) => {
            if (!updateRequirements()) {
                event.preventDefault();
                if (error instanceof HTMLElement) error.hidden = false;
                passwordInput?.focus();
                return;
            }

            if (error instanceof HTMLElement) error.hidden = true;
            disableSubmit(passwordForm);
        });
    }
});
