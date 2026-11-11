document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('profile-form');
    if (!form) return;
    const file = document.getElementById('id_photo');
    const cropValue = document.getElementById('id_photo_crop');
    const editor = document.getElementById('profile-crop-editor');
    const source = document.getElementById('profile-crop-image');
    const cropFrame = source.parentElement;
    const preview = document.getElementById('profile-photo-preview');
    const initials = document.getElementById('profile-photo-initials');
    const canvas = document.getElementById('profile-crop-preview');
    const status = document.getElementById('profile-photo-status');
    const recrop = document.getElementById('profile-recrop');
    const originalURL = preview.getAttribute('src');
    let cropper = null;
    let objectURL = null;
    let selection = null;
    let cropWidth = 0;
    let resizingCrop = false;
    let pending = false;
    const release = () => {
        cropper?.destroy(); cropper = null;
        if (objectURL) URL.revokeObjectURL(objectURL);
        objectURL = null; selection = null;
    };
    const squareCrop = rect => {
        const x = Math.max(0, Math.round(rect.x));
        const y = Math.max(0, Math.round(rect.y));
        const side = Math.min(Math.round(rect.width), Math.round(rect.height),
            source.naturalWidth - x, source.naturalHeight - y);
        return { x, y, width: side, height: side };
    };
    const draw = square => {
        if (!source.naturalWidth || square.width < 1) return;
        const context = canvas.getContext('2d');
        context.clearRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(source, square.x, square.y, square.width, square.height,
            0, 0, canvas.width, canvas.height);
    };
    const updateSelection = rect => {
        if (resizingCrop) return;
        selection = squareCrop(rect);
        draw(selection);
    };
    new ResizeObserver(() => {
        const width = cropFrame.getBoundingClientRect().width;
        if (!cropper || !selection || !width || width === cropWidth) return;

        // Croppr posiciona la selección en píxeles de pantalla. La selección guardada usa la imagen original.
        cropWidth = width;
        const scale = width / source.naturalWidth;
        const side = selection.width * scale;
        resizingCrop = true;
        cropper.resizeTo(side, side, [0, 0]).moveTo(selection.x * scale, selection.y * scale);
        resizingCrop = false;
    }).observe(cropFrame);
    file.addEventListener('change', () => {
        release(); cropValue.value = ''; recrop.hidden = true;
        const selected = file.files[0];
        pending = Boolean(selected);
        if (!selected) { editor.hidden = true; return; }
        if (!['image/jpeg', 'image/png'].includes(selected.type) || selected.size > 2 * 1024 * 1024) {
            file.value = ''; pending = false; editor.hidden = true;
            status.textContent = 'Selecciona una imagen JPEG o PNG de hasta 2 MiB.'; return;
        }
        if (!window.Croppr) {
            file.value = ''; pending = false; editor.hidden = true;
            status.textContent = 'No se pudo cargar el recortador. Recarga la página e inténtalo nuevamente.'; return;
        }
        objectURL = URL.createObjectURL(selected);
        editor.hidden = false;
        source.onload = () => {
            if (cropper) return;
            cropper = new Croppr(source, { aspectRatio: 1, startSize: [80, 80, '%'],
                onInitialize: instance => {
                    cropWidth = cropFrame.getBoundingClientRect().width;
                    updateSelection(instance.getValue());
                },
                onCropMove: updateSelection, onCropEnd: updateSelection });
        };
        source.onerror = () => { file.value = ''; pending = false; editor.hidden = true; status.textContent = 'No se pudo leer la imagen.'; };
        source.src = objectURL;
        status.textContent = 'Selecciona el área y pulsa Usar recorte.';
    });
    document.getElementById('profile-crop-apply').addEventListener('click', () => {
        if (!selection || selection.width < 1) return;
        draw(selection); cropValue.value = JSON.stringify(selection);
        preview.src = canvas.toDataURL('image/jpeg', .9);
        preview.hidden = false; initials.hidden = true;
        editor.hidden = true; recrop.hidden = false; pending = false;
        status.textContent = 'Recorte listo. Pulsa Guardar cambios para confirmar.';
    });
    recrop.addEventListener('click', () => { editor.hidden = false; pending = true; });
    document.getElementById('profile-crop-cancel').addEventListener('click', () => {
        release(); file.value = ''; cropValue.value = ''; pending = false;
        editor.hidden = true; recrop.hidden = true;
        preview.hidden = !originalURL; initials.hidden = Boolean(originalURL);
        if (originalURL) preview.src = originalURL; else preview.removeAttribute('src');
        status.textContent = 'Se conserva la foto anterior.';
    });
    form.addEventListener('submit', event => {
        if (pending) {
            event.preventDefault(); status.textContent = 'Confirma o cancela el recorte antes de guardar.';
            document.getElementById('profile-crop-apply').focus();
        }
    });
});
