document.addEventListener('DOMContentLoaded', () => {
    let target = document.querySelector('[data-client-live]');
    if (!target) return;
    const status = document.querySelector('[data-client-live-status]') || document.createElement('p');
    if (!status.isConnected) {
        status.className = 'maintainer-live-status';
        status.setAttribute('role', 'status');
        target.before(status);
    }
    status.textContent = 'Actualización automática conectada.';
    let stopped = false;
    let timer;
    const refresh = async () => {
        if (stopped) return;
        if (!stopped) {
            try {
                const response = await fetch(window.location.href, {
                    credentials: 'same-origin', cache: 'no-store', headers: {'X-Live-Search': '1'},
                });
                if (stopped) return;
                if ([401, 403, 404].includes(response.status) || response.redirected) {
                    target.replaceChildren();
                    status.textContent = 'La sesión o los permisos cambiaron. Vuelve a iniciar sesión.';
                    stopped = true;
                    return;
                }
                if (!response.ok) throw new Error('Respuesta no disponible');
                const page = new DOMParser().parseFromString(await response.text(), 'text/html');
                const fresh = page.querySelector('[data-client-live]');
                const canonical = response.headers.get("X-List-URL");
                if (canonical) window.history.replaceState(window.history.state, "", canonical);
                if (!fresh) throw new Error('Listado no disponible');
                if (target.innerHTML !== fresh.innerHTML) {
                    target = replaceLiveListRegion(target, fresh);
                    status.textContent = 'Solicitud actualizada automáticamente.';
                }
            } catch {
                status.textContent = 'No se pudo actualizar. Se intentará nuevamente.';
            }
        }
        if (!stopped) timer = window.setTimeout(refresh, 5000);
    };
    timer = window.setTimeout(refresh, 5000);
    window.addEventListener('pagehide', () => {stopped = true; window.clearTimeout(timer);});
    window.addEventListener('pageshow', event => {if (event.persisted) {stopped = false; refresh();}});
});

