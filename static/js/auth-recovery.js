// Validación en el navegador del login y la recuperación de contraseña. Los formularios
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

    const codeInputs = [...document.querySelectorAll(".code-digit")];
    const codeForm = document.querySelector("#recovery-code-form");
    if (codeInputs.length === 6 && codeForm instanceof HTMLFormElement) {
        const codeError = document.querySelector("#recovery-code-error");
        const countdown = document.querySelector("#recovery-resend-countdown");
        const resendButton = document.querySelector("#recovery-resend");

        codeInputs.forEach((input, index) => {
            input.addEventListener("input", () => {
                input.value = input.value.replace(/\D/g, "").slice(-1);
                if (input.value && index < codeInputs.length - 1) codeInputs[index + 1].focus();
                if (codeInputs.every((digit) => digit.value) && codeError instanceof HTMLElement) {
                    codeError.hidden = true;
                }
            });

            input.addEventListener("keydown", (event) => {
                if (event.key === "Backspace" && !input.value && index > 0) {
                    codeInputs[index - 1].focus();
                } else if (event.key === "ArrowLeft" && index > 0) {
                    event.preventDefault();
                    codeInputs[index - 1].focus();
                } else if (event.key === "ArrowRight" && index < codeInputs.length - 1) {
                    event.preventDefault();
                    codeInputs[index + 1].focus();
                }
            });

            input.addEventListener("paste", (event) => {
                const pastedDigits = event.clipboardData?.getData("text").replace(/\D/g, "").slice(0, 6);
                if (!pastedDigits) return;

                event.preventDefault();
                [...pastedDigits].forEach((digit, digitIndex) => {
                    codeInputs[digitIndex].value = digit;
                });
                codeInputs[Math.min(pastedDigits.length, codeInputs.length) - 1].focus();
            });
        });

        codeForm.addEventListener("submit", (event) => {
            const code = codeInputs.map((input) => input.value).join("");
            if (!/^\d{6}$/.test(code)) {
                event.preventDefault();
                if (codeError instanceof HTMLElement) {
                    codeError.textContent = "Ingresa los seis dígitos para continuar.";
                    codeError.hidden = false;
                }
                codeInputs.find((input) => !input.value)?.focus();
                return;
            }
            disableSubmit(codeForm);
        });

        if (countdown instanceof HTMLElement && resendButton instanceof HTMLButtonElement) {
            let secondsRemaining = Number(countdown.dataset.resendWait) || 0;
            const updateCountdown = () => {
                if (secondsRemaining <= 0) {
                    countdown.hidden = true;
                    resendButton.disabled = false;
                    resendButton.hidden = false;
                    return;
                }

                const minutes = String(Math.floor(secondsRemaining / 60)).padStart(2, "0");
                const seconds = String(secondsRemaining % 60).padStart(2, "0");
                countdown.textContent = `Reenviar código en ${minutes}:${seconds}`;
                secondsRemaining -= 1;
                window.setTimeout(updateCountdown, 1000);
            };
            updateCountdown();
        }
    }

    const passwordForm = document.querySelector("#recovery-password-form");
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
