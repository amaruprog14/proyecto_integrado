document.addEventListener('DOMContentLoaded', () => {
    const source = document.getElementById('client-subattention-options');
    const parent = document.getElementById('id_attention_type');
    const child = document.getElementById('id_subattention_type');
    if (!source || !parent || !child) return;
    const options = JSON.parse(source.textContent);
    const update = () => {
        const selected = child.value;
        child.replaceChildren(new Option('Selecciona una sub atención', ''));
        options.filter(option => String(option.attention_type_id) === parent.value).forEach(option => {
            child.add(new Option(option.name, option.id));
        });
        child.value = [...child.options].some(option => option.value === selected) ? selected : '';
    };
    parent.addEventListener('change', update);
    update();
});
