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

// ── Receipt Link ────────────────────────────────────────────────────────────────

async function openReceiptLink(s3Uri) {
    // Extract key from "s3://bucket/receipts/..." → "receipts/..."
    var match = s3Uri.match(/^s3:\/\/[^/]+\/(.+)$/);
    if (!match) return;

    var token = await getAccessToken();
    var response = await fetch(CONFIG.apiEndpoint + "/receipt?key=" + encodeURIComponent(match[1]), {
        headers: { "Authorization": "Bearer " + token },
    });
    if (!response.ok) {
        alert("Failed to get receipt URL: " + response.status);
        return;
    }
    var data = await response.json();
    window.open(data.url, "_blank");
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
            cellEditor: "agSelectCellEditor",
            cellEditorParams: {
                values: ["CHRIS", "JILLIAN", "KAYA", "MATEO", "UNKNOWN"],
            },
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
            editable: true,
            width: 200,
            cellDataType: "text",
        },
        {
            headerName: "Receipt",
            editable: false,
            width: 90,
            sortable: false,
            filter: false,
            cellRenderer: function (params) {
                var uri = params.data["Receipt S3 URI"];
                if (!uri) return "";
                var link = document.createElement("a");
                link.textContent = "Download";
                link.href = "#";
                link.addEventListener("click", function (e) {
                    e.preventDefault();
                    openReceiptLink(uri);
                });
                return link;
            },
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
            headerName: "Dup. %",
            editable: false,
            width: 100,
            cellDataType: "text",
            valueGetter: function (params) {
                return params.data["Prob. of Duplicate"];
            },
            valueSetter: function (params) {
                params.data["Prob. of Duplicate"] = params.newValue;
                return true;
            },
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

function handleDownload() {
    const allData = getAllRowData();
    const csvString = serializeCsv(allData);
    const blob = new Blob([csvString], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "hsa-receipts.csv";
    a.click();
    URL.revokeObjectURL(url);
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
    document.getElementById("download-btn").addEventListener("click", handleDownload);

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
