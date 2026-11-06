document.addEventListener('DOMContentLoaded', () => {
    const configure = form => {
        const parent = form.querySelector('[name="delegation"]');
        const child = form.querySelector('[data-client-territory]');
        if (parent && child && !child.dataset.ready) {
            child.dataset.ready = 'true';
            const options = [...child.options].map(option => option.cloneNode(true));
            const update = clear => {
                const selected = clear ? '' : child.value;
                child.replaceChildren(...options.filter(option => !option.value || option.dataset.delegation === parent.value).map(option => option.cloneNode(true)));
                child.value = [...child.options].some(option => option.value === selected) ? selected : '';
            };
            parent.addEventListener('change', () => update(true));
            update(false);
        }
    };
    document.querySelectorAll('form').forEach(configure);
    document.addEventListener('sgr:modal-form-loaded', event => configure(event.detail.form));
    document.addEventListener('change', async event => {
        if (!event.target.matches('[data-account-type]') || event.target.disabled) return;
        const selector = event.target;
        const form = selector.form;
        if (!selector.value) return;
        const url = new URL(form.action || location.href);
        url.searchParams.set('account_type', selector.value);
        const oldValues = new FormData(form);
        selector.disabled = true;
        try {
            const response = await fetch(url, {credentials:'same-origin', headers:{'X-Modal-Request':'true'}});
            if (!response.ok || response.redirected) throw new Error('Formulario no disponible');
            const page = new DOMParser().parseFromString(await response.text(), 'text/html');
            const fresh = page.querySelector('main form[method="post"]');
            if (!fresh) throw new Error('Formulario no disponible');
            fresh.action = form.action;
            if (form.dataset.modalForm) fresh.dataset.modalForm = 'true';
            fresh.classList.toggle('maintainer-modal-form', !!form.dataset.modalForm);
            if (form.dataset.modalForm) fresh.classList.remove('attention-entry-card');
            // Conservar únicamente datos comunes de identidad y contacto.
            ['username','first_name','last_name','email','national_id','phone','password1','password2'].forEach(name => {
                const input = fresh.elements.namedItem(name);
                if (input && oldValues.has(name)) input.value = oldValues.get(name);
            });
            form.replaceWith(fresh);
            document.dispatchEvent(new CustomEvent('sgr:modal-form-loaded',{detail:{form:fresh}}));
        } catch {
            selector.disabled = false;
            const alert = document.createElement('p');
            alert.setAttribute('role','alert');
            alert.className = 'text-danger';
            alert.textContent = 'No se pudo cambiar el formulario. Vuelve a seleccionar el tipo.';
            form.prepend(alert);
        }
    });
});
