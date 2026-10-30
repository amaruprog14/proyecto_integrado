// Búsqueda, filtro por estado y paginación en el navegador para las tablas que se cargan
// completas (Funcionarios y las maquetas). La búsqueda compara solo las columnas de datos, no
// la de acciones. Si la página tiene un enlace de exportación con data-export-url, este se
// actualiza con la búsqueda y el estado elegidos para que el servidor exporte las mismas filas.
document.addEventListener("DOMContentLoaded", () => {
    const table = document.querySelector("#maintainer-table");
    const searchInput = document.querySelector("#maintainer-search");
    const statusFilter = document.querySelector("#maintainer-status");
    const pagination = document.querySelector("#maintainer-pagination");
    const recordCount = document.querySelector("#maintainer-record-count");
    const emptyMessage = document.querySelector("#maintainer-empty");
    const exportLink = document.querySelector("a[data-export-url]");

    if (!table || !searchInput || !pagination || !recordCount || !emptyMessage) {
        return;
    }

    const rows = [...table.tBodies[0].rows];
    const pageSizeSelect = document.querySelector("#maintainer-page-size");
    let pageSize = Number.parseInt(pageSizeSelect?.value || table.dataset.pageSize || "10", 10);
    const rowText = (row) =>
        [...row.cells]
            .slice(0, -1)
            .map((cell) => cell.textContent)
            .join(" ")
            .toLocaleLowerCase();
    let currentPage = 1;

    const getFilteredRows = () => {
        const query = searchInput.value.trim().toLocaleLowerCase();
        const status = statusFilter ? statusFilter.value : "";

        return rows.filter((row) => {
            const matchesQuery = rowText(row).includes(query);
            const matchesStatus = !status || row.dataset.status === status;
            return matchesQuery && matchesStatus;
        });
    };

    const updateExportLink = () => {
        if (!exportLink) return;
        const params = new URLSearchParams();
        const query = searchInput.value.trim();
        if (query) params.set("q", query);
        if (statusFilter?.value) params.set("status", statusFilter.value);
        const search = params.toString();
        exportLink.href = search ? `${exportLink.dataset.exportUrl}?${search}` : exportLink.dataset.exportUrl;
    };

    const renderPagination = (pageCount) => {
        pagination.replaceChildren();

        const addPageButton = (label, page, disabled = false, current = false) => {
            const item = document.createElement("li");
            item.className = `page-item${disabled ? " disabled" : ""}${current ? " active" : ""}`;

            const button = document.createElement("button");
            button.className = "page-link";
            button.type = "button";
            button.textContent = label;
            button.disabled = disabled;
            if (current) button.setAttribute("aria-current", "page");
            button.addEventListener("click", () => {
                currentPage = page;
                render();
            });

            item.append(button);
            pagination.append(item);
        };

        addPageButton("Anterior", Math.max(1, currentPage - 1), currentPage === 1);
        for (let page = 1; page <= pageCount; page += 1) {
            addPageButton(String(page), page, false, page === currentPage);
        }
        addPageButton("Siguiente", Math.min(pageCount, currentPage + 1), currentPage === pageCount);
    };

    const render = () => {
        const filteredRows = getFilteredRows();
        const pageCount = Math.max(1, Math.ceil(filteredRows.length / pageSize));
        currentPage = Math.min(currentPage, pageCount);
        const start = (currentPage - 1) * pageSize;
        const visibleRows = new Set(filteredRows.slice(start, start + pageSize));

        rows.forEach((row) => {
            row.hidden = !visibleRows.has(row);
        });

        const firstRecord = filteredRows.length ? start + 1 : 0;
        const lastRecord = Math.min(start + pageSize, filteredRows.length);
        recordCount.textContent = `Mostrando ${firstRecord} a ${lastRecord} de ${filteredRows.length} registros`;
        emptyMessage.hidden = filteredRows.length !== 0;
        renderPagination(pageCount);
        updateExportLink();
    };

    searchInput.addEventListener("input", () => {
        currentPage = 1;
        render();
    });
    statusFilter?.addEventListener("change", () => {
        currentPage = 1;
        render();
    });

    document.querySelector("[data-maintainer-search]")?.addEventListener("click", () => {
        currentPage = 1;
        render();
    });
    pageSizeSelect?.addEventListener("change", () => {
        pageSize = Number.parseInt(pageSizeSelect.value, 10);
        currentPage = 1;
        render();
    });
    render();
});
