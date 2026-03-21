// Ledger editor — fetch, display, edit, and save the HSA receipt CSV ledger.

const LEDGER_HEADERS = [
    "Id", "Service Date", "Payment Date", "Vendor/Provider",
    "Patient/For", "Category", "Description", "Amount",
    "Receipt S3 URI", "Reimbursed", "Notes", "Prob. of Duplicate",
];

let gridApi = null;
let isDirty = false;

// ── API ─────────────────────────────────────────────────────────────────────────

async function fetchLedger() {
    const token = await getAccessToken();
    const response = await fetch(`${CONFIG.apiEndpoint}/ledger`, {
        headers: { "Authorization": `Bearer ${token}` },
    });
    if (!response.ok) {
        throw new Error(`Failed to fetch ledger: ${response.status}`);
    }
    return await response.text();
}

async function saveLedger(csvString) {
    const token = await getAccessToken();
    const response = await fetch(`${CONFIG.apiEndpoint}/ledger`, {
        method: "PUT",
        headers: {
            "Authorization": `Bearer ${token}`,
            "Content-Type": "text/csv",
        },
        body: csvString,
    });
    if (!response.ok) {
        throw new Error(`Failed to save ledger: ${response.status}`);
    }
    return await response.text();
}

// ── CSV ─────────────────────────────────────────────────────────────────────────

function parseCsv(csvString) {
    const result = Papa.parse(csvString.trim(), {
        header: true,
        skipEmptyLines: true,
    });
    return result.data;
}

function serializeCsv(rowData) {
    return Papa.unparse({
        fields: LEDGER_HEADERS,
        data: rowData,
    });
}

// ── Value Setters & Formatters ──────────────────────────────────────────────────

function dateValueSetter(params) {
    const newValue = params.newValue.trim();
    if (newValue === "") {
        params.data[params.colDef.field] = "";
        return true;
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(newValue) && !isNaN(Date.parse(newValue))) {
        params.data[params.colDef.field] = newValue;
        return true;
    }
    return false;
}

function amountValueSetter(params) {
    const newValue = params.newValue.trim();
    if (newValue === "") {
        params.data[params.colDef.field] = "";
        return true;
    }
    const cleaned = newValue.replace(/^\$/, "");
    const parsed = parseFloat(cleaned);
    if (!isNaN(parsed) && parsed >= 0) {
        params.data[params.colDef.field] = parsed.toFixed(2);
        return true;
    }
    return false;
}

function amountFormatter(params) {
    if (!params.value || params.value === "") return "";
    return "$" + params.value;
}

// ── Column Definitions ──────────────────────────────────────────────────────────

function getColumnDefs() {
    return [
        {
            field: "Id",
            editable: false,
            width: 70,
            cellDataType: "text",
        },
        {
            field: "Service Date",
            editable: true,
            width: 130,
            cellDataType: "text",
            valueSetter: dateValueSetter,
        },
        {
            field: "Payment Date",
            editable: true,
            width: 130,
            cellDataType: "text",
            valueSetter: dateValueSetter,
        },
        {
            field: "Vendor/Provider",
            editable: true,
            width: 200,
            cellDataType: "text",
        },
        {
            field: "Patient/For",
            editable: true,
            width: 130,
            cellDataType: "text",
        },
        {
            field: "Category",
            editable: true,
            width: 130,
            cellDataType: "text",
            cellEditor: "agSelectCellEditor",
            cellEditorParams: {
                values: [
                    "", "Medical", "Dental", "Vision", "Pharmacy",
                    "Mental Health", "Lab/Imaging", "Other",
                ],
            },
        },
        {
            field: "Description",
            editable: true,
            flex: 1,
            minWidth: 200,
            cellDataType: "text",
        },
        {
            field: "Amount",
            editable: true,
            width: 110,
            cellDataType: "text",
            valueSetter: amountValueSetter,
            valueFormatter: amountFormatter,
        },
        {
            field: "Receipt S3 URI",
            editable: false,
            width: 200,
            cellDataType: "text",
        },
        {
            field: "Reimbursed",
            editable: true,
            width: 120,
            cellDataType: "text",
            cellEditor: "agSelectCellEditor",
            cellEditorParams: {
                values: ["No", "Yes"],
            },
        },
        {
            field: "Notes",
            editable: true,
            width: 200,
            cellDataType: "text",
        },
        {
            field: "Prob. of Duplicate",
            editable: false,
            width: 100,
            cellDataType: "text",
            headerName: "Dup. %",
        },
    ];
}

// ── Grid Setup ──────────────────────────────────────────────────────────────────

function createGrid(rowData) {
    const gridDiv = document.getElementById("ledger-grid");
    const gridOptions = {
        theme: agGrid.themeQuartz,
        columnDefs: getColumnDefs(),
        rowData: rowData,
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true,
            minWidth: 80,
        },
        rowSelection: {
            mode: "multiRow",
        },
        onCellValueChanged: function () {
            markDirty();
        },
        undoRedoCellEditing: true,
        undoRedoCellEditingLimit: 50,
        stopEditingWhenCellsLoseFocus: true,
    };
    gridApi = agGrid.createGrid(gridDiv, gridOptions);
}

// ── Dirty State ─────────────────────────────────────────────────────────────────

function markDirty() {
    if (!isDirty) {
        isDirty = true;
        document.getElementById("unsaved-indicator").classList.remove("hidden");
    }
}

function markClean() {
    isDirty = false;
    document.getElementById("unsaved-indicator").classList.add("hidden");
}

// ── Toolbar Actions ─────────────────────────────────────────────────────────────

function getAllRowData() {
    const rowData = [];
    gridApi.forEachNode(function (node) {
        rowData.push(node.data);
    });
    return rowData;
}

function addRow() {
    const allData = getAllRowData();
    const maxId = allData.reduce(function (max, row) {
        const id = parseInt(row["Id"], 10);
        return isNaN(id) ? max : Math.max(max, id);
    }, 0);

    const newRow = {};
    for (const header of LEDGER_HEADERS) {
        newRow[header] = "";
    }
    newRow["Id"] = String(maxId + 1);
    newRow["Reimbursed"] = "No";

    gridApi.applyTransaction({ add: [newRow] });
    markDirty();
}

function deleteSelectedRows() {
    const selectedRows = gridApi.getSelectedRows();
    if (selectedRows.length === 0) {
        showStatus("No rows selected", "info");
        return;
    }
    const count = selectedRows.length;
    if (!confirm("Delete " + count + " selected row" + (count > 1 ? "s" : "") + "?")) {
        return;
    }
    gridApi.applyTransaction({ remove: selectedRows });
    markDirty();
}

async function handleSave() {
    if (!confirm("Save changes to the ledger?")) {
        return;
    }

    const allData = getAllRowData();
    const csvString = serializeCsv(allData);

    showStatus("Saving...", "info");
    try {
        await saveLedger(csvString);
        markClean();
        showStatus("Saved successfully", "success");
    } catch (err) {
        showStatus("Save failed: " + err.message, "error");
    }
}

// ── Status ──────────────────────────────────────────────────────────────────────

function showStatus(message, type) {
    const el = document.getElementById("status-message");
    el.textContent = message;
    el.className = "status-" + type;
    if (type === "success") {
        setTimeout(function () {
            el.textContent = "";
            el.className = "";
        }, 3000);
    }
}

// ── Init ────────────────────────────────────────────────────────────────────────

async function initLedger() {
    document.getElementById("add-row-btn").addEventListener("click", addRow);
    document.getElementById("delete-rows-btn").addEventListener("click", deleteSelectedRows);
    document.getElementById("save-btn").addEventListener("click", handleSave);

    window.addEventListener("beforeunload", function (e) {
        if (isDirty) {
            e.preventDefault();
        }
    });

    showStatus("Loading ledger...", "info");
    try {
        const csv = await fetchLedger();
        const rowData = parseCsv(csv);
        createGrid(rowData);
        showStatus("", "info");
    } catch (err) {
        const container = document.getElementById("grid-container");
        container.innerHTML =
            "<div id=\"load-error\">" +
            "<p>Failed to load ledger: " + err.message + "</p>" +
            "<button onclick=\"location.reload()\">Retry</button>" +
            "</div>";
    }
}
