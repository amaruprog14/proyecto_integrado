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

    const requestForm = document.querySelector("#recovery-request-form");
    if (requestForm instanceof HTMLFormElement) {
        const emailInput = document.querySelector("#recovery-email");
        const emailError = document.querySelector("#recovery-email-error");
        const feedback = document.querySelector("#recovery-request-feedback");
        const continueLink = document.querySelector("#recovery-request-continue");

        requestForm.addEventListener("submit", (event) => {
            event.preventDefault();
            if (
                !(emailInput instanceof HTMLInputElement) ||
                !(emailError instanceof HTMLElement) ||
                !(feedback instanceof HTMLElement) ||
                !(continueLink instanceof HTMLAnchorElement)
            ) {
                return;
            }

            if (!emailInput.validity.valid || !emailInput.value.trim()) {
                emailError.hidden = false;
                emailInput.setAttribute("aria-invalid", "true");
                emailInput.focus();
                return;
            }

            emailError.hidden = true;
            emailInput.removeAttribute("aria-invalid");
            sessionStorage.setItem("sgr-recovery-email", emailInput.value.trim());
            continueLink.href = requestForm.dataset.nextUrl || continueLink.href;
            feedback.hidden = false;
            continueLink.hidden = false;
        });
    }

    const codeInputs = [...document.querySelectorAll(".code-digit")];
    const codeForm = document.querySelector("#recovery-code-form");
    if (codeInputs.length === 6 && codeForm instanceof HTMLFormElement) {
        const emailLabel = document.querySelector("#recovery-email-masked");
        const savedEmail = sessionStorage.getItem("sgr-recovery-email");
        if (emailLabel instanceof HTMLElement && savedEmail) {
            const [name, domain] = savedEmail.split("@");
            emailLabel.textContent = domain
                ? `${name.slice(0, 1)}***@${domain}`
                : "u***@example.test";
        }

        const codeError = document.querySelector("#recovery-code-error");
        const countdown = document.querySelector("#recovery-resend-countdown");
        const resendButton = document.querySelector("#recovery-resend");
        const resendFeedback = document.querySelector("#recovery-resend-feedback");

        codeInputs.forEach((input, index) => {
            input.addEventListener("input", () => {
                input.value = input.value.replace(/\D/g, "").slice(-1);
                if (input.value && index < codeInputs.length - 1) codeInputs[index + 1].focus();
                if (codeInputs.every((digit) => digit.value)) {
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
            event.preventDefault();
            const code = codeInputs.map((input) => input.value).join("");
            if (!/^\d{6}$/.test(code)) {
                codeError.hidden = false;
                codeInputs.find((input) => !input.value)?.focus();
                return;
            }

            codeError.hidden = true;
            window.location.assign(codeForm.dataset.nextUrl);
        });

        if (
            countdown instanceof HTMLElement &&
            resendButton instanceof HTMLButtonElement &&
            resendFeedback instanceof HTMLElement
        ) {
            let secondsRemaining = 45;
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

            resendButton.addEventListener("click", () => {
                resendFeedback.hidden = false;
                resendButton.disabled = true;
                resendButton.hidden = true;
                countdown.hidden = false;
                secondsRemaining = 45;
                updateCountdown();
            });
        }
    }

    const passwordForm = document.querySelector("#recovery-password-form");
    if (passwordForm instanceof HTMLFormElement) {
        const passwordInput = document.querySelector("#new-password");
        const confirmationInput = document.querySelector("#confirm-password");
        const error = document.querySelector("#recovery-password-error");
        const success = document.querySelector("#recovery-password-success");
        const successDialog = document.querySelector("#recovery-success-dialog");
        const closeSuccess = document.querySelector("#recovery-success-close");
        const requirements = {
            length: (value) => value.length >= 8,
            uppercase: (value) => /[A-Z]/.test(value),
            lowercase: (value) => /[a-z]/.test(value),
            number: (value) => /\d/.test(value),
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
            event.preventDefault();
            const isValid = updateRequirements();
            if (!isValid) {
                error.hidden = false;
                passwordInput?.focus();
                return;
            }

            error.hidden = true;
            if (window.Swal) {
                window.Swal.fire({
                    title: "Validación completada (demo)",
                    text: "La contraseña cumple los requisitos, pero no se ha guardado.",
                    icon: "success",
                    confirmButtonText: "Entendido",
                    confirmButtonColor: "#ad0000",
                }).then(() => {
                    success.hidden = false;
                });
            } else {
                successDialog.showModal();
            }
        });

        closeSuccess?.addEventListener("click", () => {
            successDialog.close();
            success.hidden = false;
        });
    }
});
