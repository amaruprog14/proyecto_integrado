function replaceLiveListRegion(region, freshRegion) {
    const replacement = document.importNode(freshRegion, true);
    const tableSelector = ".maintainer-table-wrap";
    const currentTable = region.matches(tableSelector) ? region : region.querySelector(tableSelector);
    const nextTable = replacement.matches(tableSelector) ? replacement : replacement.querySelector(tableSelector);
    const scrollLeft = currentTable?.scrollLeft ?? 0;
    const focused = region.contains(document.activeElement) ? document.activeElement : null;

    region.replaceWith(replacement);
    if (nextTable) nextTable.scrollLeft = scrollLeft;

    if (focused) {
        const href = focused.getAttribute("href");
        const formAction = focused.form?.getAttribute("action");
        const control = [...replacement.querySelectorAll("a[href], button[type=submit]:enabled")].find(
            element => href
                ? element.getAttribute("href") === href
                : formAction && element.form?.getAttribute("action") === formAction,
        );
        (control ?? nextTable)?.focus({ preventScroll: true });
    }
    return replacement;
}
