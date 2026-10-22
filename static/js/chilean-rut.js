(() => {
    const invalidMessage = "Ingresa un RUT o RUN chileno válido.";
    const rutPattern = /^(?:\d{1,2}(?:\.\d{3}){1,2}|\d{1,8})-?[\dK]$/;

    const isValidRut = (value) => {
        const rut = value.trim().toUpperCase();
        if (!rutPattern.test(rut)) return false;

        const digits = rut.replace(/[.-]/g, "");
        const number = digits.slice(0, -1);
        const checkDigit = digits.slice(-1);
        let weightedSum = 0;
        let factor = 2;

        for (let index = number.length - 1; index >= 0; index -= 1) {
            weightedSum += Number(number[index]) * factor;
            factor = factor === 7 ? 2 : factor + 1;
        }

        const remainder = 11 - (weightedSum % 11);
        const expectedDigit = remainder === 11 ? "0" : remainder === 10 ? "K" : String(remainder);
        return checkDigit === expectedDigit;
    };

    document.querySelectorAll("input[data-chilean-rut]").forEach((input) => {
        const validate = () => {
            const value = input.value.trim();
            input.setCustomValidity(value && !isValidRut(value) ? invalidMessage : "");
        };

        input.addEventListener("input", validate);
        input.addEventListener("change", validate);
        validate();
    });
})();
