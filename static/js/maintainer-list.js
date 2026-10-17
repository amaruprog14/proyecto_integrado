document.addEventListener("DOMContentLoaded", () => {
    const table = document.querySelector("#maintainer-table");
    const searchInput = document.querySelector("#maintainer-search");
    const statusFilter = document.querySelector("#maintainer-status");
    const pagination = document.querySelector("#maintainer-pagination");
    const recordCount = document.querySelector("#maintainer-record-count");
    const emptyMessage = document.querySelector("#maintainer-empty");
    const exportButton = document.querySelector("#maintainer-export");

    if (
        !table ||
        !searchInput ||
        !pagination ||
        !recordCount ||
        !emptyMessage ||
        !exportButton
    ) {
        return;
    }

    const rows = [...table.tBodies[0].rows];
    const pageSize = Number.parseInt(table.dataset.pageSize || "3", 10);
    let currentPage = 1;

    const getFilteredRows = () => {
        const query = searchInput.value.trim().toLocaleLowerCase();
        const status = statusFilter ? statusFilter.value : "";

        return rows.filter((row) => {
            const matchesQuery = row.textContent.toLocaleLowerCase().includes(query);
            const matchesStatus = !status || row.dataset.status === status;
            return matchesQuery && matchesStatus;
        });
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
    };

    searchInput.addEventListener("input", () => {
        currentPage = 1;
        render();
    });
    statusFilter?.addEventListener("change", () => {
        currentPage = 1;
        render();
    });
    exportButton.addEventListener("click", () => {
        const visibleRows = getFilteredRows();
        const headers = [...table.tHead.rows[0].cells]
            .slice(0, -1)
            .map((cell) => cell.textContent.trim());
        const lines = [
            headers,
            ...visibleRows.map((row) =>
                [...row.cells]
                    .slice(0, -1)
                    .map((cell) => cell.textContent.trim().replace(/\s+/g, " ")),
            ),
        ];
        const csv = `\uFEFF${lines
            .map((line) => line.map((value) => `"${value.replaceAll('"', '""')}"`).join(";"))
            .join("\r\n")}`;
        const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `${table.dataset.exportFilename || "registros"}.csv`;
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

    render();
});
