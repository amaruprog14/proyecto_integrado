// Confirmaciones y ayudas de los mantenedores de Delegaciones y Usuarios.
//
// - Intercepta los formularios marcados con data-swal-confirm y pide confirmación con
//   SweetAlert2 antes de desactivar o activar un registro. Si SweetAlert2 no carga, el
//   formulario se envía igual (nunca se bloquea una operación). El listener está en el
//   documento para cubrir también las filas que la búsqueda en tiempo real vuelve a dibujar.
// - Los controles marcados con data-swal-autosubmit envían su formulario al cambiar, salvo que
//   la búsqueda en tiempo real (maintainer-states.js) ya actualice el listado sin recargar.
document.addEventListener("DOMContentLoaded", () => {
    const confirmColor = () =>
        getComputedStyle(document.documentElement).getPropertyValue("--color-primary").trim() || "#ad0000";

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.matches("form[data-swal-confirm]")) return;
        if (form.dataset.swalConfirmed === "true") return;
        if (!window.Swal) return;

        event.preventDefault();
        window.Swal.fire({
            title: form.dataset.swalTitle || "Confirmar acción",
            text: form.dataset.swalConfirm,
            icon: form.dataset.swalIcon || "warning",
            showCancelButton: true,
            confirmButtonText: form.dataset.swalConfirmText || "Sí, continuar",
            cancelButtonText: "Cancelar",
            confirmButtonColor: confirmColor(),
        }).then((result) => {
            if (result.isConfirmed) {
                form.dataset.swalConfirmed = "true";
                form.submit();
            }
        });
    });

    document.querySelectorAll("[data-swal-autosubmit]").forEach((element) => {
        element.addEventListener("change", () => {
            const form = element.closest("form");
            if (form && form.dataset.liveSearchReady !== "true") form.submit();
        });
    });

    const initializeUserForm = (userForm) => {

    const firstName = userForm.querySelector("#id_first_name");
    const lastName = userForm.querySelector("#id_last_name");
    const username = userForm.querySelector("#id_username");
    const fullName = userForm.querySelector("#id_full_name");
    const mode = userForm.dataset.userFormMode || userForm.dataset.officialFormMode;
    const existingElement =
        userForm.parentElement.querySelector("#existing-usernames") ||
        document.getElementById("existing-usernames");
    const existingUsernames = new Set(
        existingElement ? JSON.parse(existingElement.textContent).map((value) => value.toLocaleLowerCase()) : [],
    );

    const createAccount = userForm.querySelector("#id_create_account");
    const accountFields = userForm.querySelector("[data-account-fields]");
    const syncAccountFields = () => {
        if (!createAccount || !accountFields) return;
        accountFields.hidden = !createAccount.checked;
        accountFields.querySelectorAll("input").forEach((input) => {
            input.disabled = !createAccount.checked;
        });
    };
    createAccount?.addEventListener("change", syncAccountFields);
    syncAccountFields();

    const words = (value) => value.trim().replace(/\s+/g, " ").split(" ").filter(Boolean);
    const titleCase = (value) =>
        words(value)
            .map((word) => word.charAt(0).toLocaleUpperCase("es-CL") + word.slice(1).toLocaleLowerCase("es-CL"))
            .join(" ");
    const usernameBase = (value) =>
        value
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .replace(/[^a-zA-Z0-9]+/g, " ")
            .trim()
            .split(/\s+/)
            .filter(Boolean)
            .join(".")
            .toLocaleLowerCase("en-US");
    const availableUsername = (base) => {
        if (!base || !existingUsernames.has(base)) return base;
        let suffix = 2;
        while (existingUsernames.has(`${base}${suffix}`)) suffix += 1;
        return `${base}${suffix}`;
    };

    let usernameAutomatic = mode === "create";
    let fullNameAutomatic = mode === "create";
    let generatedUsername = "";
    let generatedFullName = "";
    let writingDerivedValue = false;

    const updateDerivedNames = () => {
        const combined = `${firstName?.value || ""} ${lastName?.value || ""}`;
        const formattedFullName = titleCase(combined);
        const normalizedUsername = firstName?.value.trim() && lastName?.value.trim()
            ? availableUsername(usernameBase(combined))
            : "";

        if (fullName && fullNameAutomatic) {
            writingDerivedValue = true;
            fullName.value = formattedFullName;
            generatedFullName = formattedFullName;
            writingDerivedValue = false;
        }
        if (username && usernameAutomatic) {
            writingDerivedValue = true;
            username.value = normalizedUsername;
            generatedUsername = normalizedUsername;
            writingDerivedValue = false;
        }
    };

    if (firstName && lastName && username && fullName) {
        if (mode === "edit") {
            const initialFullName = titleCase(`${firstName.value} ${lastName.value}`);
            const initialUsername = usernameBase(`${firstName.value} ${lastName.value}`);
            fullNameAutomatic = fullName.value === initialFullName;
            usernameAutomatic = Boolean(firstName.value.trim() && lastName.value.trim()) &&
                username.value === availableUsername(initialUsername);
        }
        firstName.addEventListener("input", updateDerivedNames);
        lastName.addEventListener("input", updateDerivedNames);
        username.addEventListener("input", () => {
            if (!writingDerivedValue) usernameAutomatic = false;
        });
        fullName.addEventListener("input", () => {
            if (!writingDerivedValue) fullNameAutomatic = false;
        });
    }

    // Los roles privilegiados que el actor no puede asignar llegan bloqueados (data-role-locked)
    // desde el servidor: aquí no se habilitan ni se desmarcan.
    const roleInputs = [...userForm.querySelectorAll('input[name="roles"]')];
    const applyRoleSelection = () => {
        const administrator = roleInputs.find((input) =>
            input.dataset.roleGlobalAdministrator === "true" && input.checked,
        );
        roleInputs.forEach((input) => {
            if (input.dataset.roleLocked === "true") return;
            if (administrator && input !== administrator) {
                input.checked = false;
                input.disabled = true;
            } else {
                input.disabled = false;
            }
        });
    };
    roleInputs.forEach((input) => input.addEventListener("change", applyRoleSelection));
    applyRoleSelection();

    const principal = userForm.querySelector("#id_delegation");
    const additionalDelegations = [...userForm.querySelectorAll('input[name="authorized_delegations"]')];
    let previousPrincipal = principal?.value || "";
    const syncDelegations = () => {
        if (previousPrincipal) {
            const previous = additionalDelegations.find((input) => input.value === previousPrincipal);
            if (previous) previous.disabled = false;
        }
        const currentPrincipal = principal?.value || "";
        const current = additionalDelegations.find((input) => input.value === currentPrincipal);
        if (current) {
            current.checked = false;
            current.disabled = true;
        }
        previousPrincipal = currentPrincipal;
    };
    principal?.addEventListener("change", syncDelegations);
    syncDelegations();

    };

    const userForm = document.querySelector("form[data-user-form-mode], form[data-official-form-mode]");
    if (userForm) initializeUserForm(userForm);
    document.addEventListener("sgr:modal-form-loaded", (event) => {
        if (event.detail.form.matches("form[data-user-form-mode], form[data-official-form-mode]")) {
            initializeUserForm(event.detail.form);
        }
    });
});
