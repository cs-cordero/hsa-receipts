// Orphaned receipts — detect and manage S3 objects with no ledger reference.

// ── API ─────────────────────────────────────────────────────────────────────────

async function fetchOrphanedReceipts() {
    var token = await getAccessToken();
    var response = await fetch(CONFIG.apiEndpoint + "/orphaned-receipts", {
        headers: { "Authorization": "Bearer " + token },
    });
    if (!response.ok) {
        throw new Error("Failed to detect orphaned receipts: " + response.status);
    }
    return await response.json();
}

async function deleteReceipt(key) {
    var token = await getAccessToken();
    var response = await fetch(CONFIG.apiEndpoint + "/receipt?key=" + encodeURIComponent(key), {
        method: "DELETE",
        headers: { "Authorization": "Bearer " + token },
    });
    if (!response.ok) {
        throw new Error("Failed to delete receipt: " + response.status);
    }
    return await response.json();
}

async function openOrphanedReceipt(key) {
    var token = await getAccessToken();
    var response = await fetch(CONFIG.apiEndpoint + "/receipt?key=" + encodeURIComponent(key), {
        headers: { "Authorization": "Bearer " + token },
    });
    if (!response.ok) {
        alert("Failed to get receipt URL: " + response.status);
        return;
    }
    var data = await response.json();
    window.open(data.url, "_blank");
}

// ── Helpers ──────────────────────────────────────────────────────────────────────

function extractKeyFromUri(s3Uri) {
    var match = s3Uri.match(/^s3:\/\/[^/]+\/(.+)$/);
    return match ? match[1] : null;
}

function escapeHtmlOrphaned(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// ── Rendering ────────────────────────────────────────────────────────────────────

function renderOrphanedTable(orphanedReceipts) {
    var container = document.getElementById("orphaned-table-container");
    container.innerHTML = "";

    if (orphanedReceipts.length === 0) {
        container.innerHTML = "<p class=\"no-results\">No orphaned receipts found.</p>";
        return;
    }

    var table = document.createElement("table");
    table.className = "results-table";
    table.innerHTML =
        "<thead><tr>" +
        "<th>S3 URI</th>" +
        "<th>View</th>" +
        "<th>Delete</th>" +
        "</tr></thead>";

    var tbody = document.createElement("tbody");
    for (var i = 0; i < orphanedReceipts.length; i++) {
        var uri = orphanedReceipts[i];
        var key = extractKeyFromUri(uri);
        var tr = document.createElement("tr");

        // Column 1: S3 URI as plain, copyable text
        var tdUri = document.createElement("td");
        tdUri.className = "s3-uri-cell";
        var code = document.createElement("code");
        code.textContent = uri;
        tdUri.appendChild(code);
        tr.appendChild(tdUri);

        // Column 2: View link
        var tdView = document.createElement("td");
        if (key) {
            var viewLink = document.createElement("a");
            viewLink.textContent = "View";
            viewLink.href = "#";
            viewLink.setAttribute("data-key", key);
            viewLink.addEventListener("click", function (e) {
                e.preventDefault();
                openOrphanedReceipt(this.getAttribute("data-key"));
            });
            tdView.appendChild(viewLink);
        }
        tr.appendChild(tdView);

        // Column 3: Delete button
        var tdDelete = document.createElement("td");
        if (key) {
            var deleteBtn = document.createElement("button");
            deleteBtn.textContent = "Delete";
            deleteBtn.className = "delete-btn";
            deleteBtn.setAttribute("data-key", key);
            deleteBtn.setAttribute("data-uri", uri);
            deleteBtn.addEventListener("click", function () {
                handleDelete(this);
            });
            tdDelete.appendChild(deleteBtn);
        }
        tr.appendChild(tdDelete);

        tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    container.appendChild(table);
}

function renderBrokenTable(brokenReferences) {
    var container = document.getElementById("broken-table-container");
    container.innerHTML = "";

    if (brokenReferences.length === 0) {
        container.innerHTML = "<p class=\"no-results\">No broken references found.</p>";
        return;
    }

    var table = document.createElement("table");
    table.className = "results-table";
    table.innerHTML =
        "<thead><tr>" +
        "<th>Id</th>" +
        "<th>Service Date</th>" +
        "<th>Provider</th>" +
        "<th>Description</th>" +
        "<th>Amount</th>" +
        "<th>Receipt S3 URI</th>" +
        "</tr></thead>";

    var tbody = document.createElement("tbody");
    for (var i = 0; i < brokenReferences.length; i++) {
        var row = brokenReferences[i];
        var tr = document.createElement("tr");
        tr.innerHTML =
            "<td>" + escapeHtmlOrphaned(row["Id"] || "") + "</td>" +
            "<td>" + escapeHtmlOrphaned(row["Service Date"] || "") + "</td>" +
            "<td>" + escapeHtmlOrphaned(row["Vendor/Provider"] || "") + "</td>" +
            "<td>" + escapeHtmlOrphaned(row["Description"] || "") + "</td>" +
            "<td>" + (row["Amount"] ? "$" + escapeHtmlOrphaned(row["Amount"]) : "") + "</td>" +
            "<td><code>" + escapeHtmlOrphaned(row["Receipt S3 URI"] || "") + "</code></td>";
        tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    container.appendChild(table);
}

// ── Delete Handler ───────────────────────────────────────────────────────────────

async function handleDelete(btn) {
    var key = btn.getAttribute("data-key");
    var uri = btn.getAttribute("data-uri");
    if (!confirm("Delete " + uri + "?\n\nThis cannot be undone.")) {
        return;
    }

    btn.disabled = true;
    btn.textContent = "Deleting...";

    try {
        await deleteReceipt(key);
        var row = btn.closest("tr");
        row.remove();
        showDetectStatus("Deleted " + key, "success");
    } catch (err) {
        btn.disabled = false;
        btn.textContent = "Delete";
        showDetectStatus("Delete failed: " + err.message, "error");
    }
}

// ── Status ───────────────────────────────────────────────────────────────────────

function showDetectStatus(message, type) {
    var el = document.getElementById("detect-status");
    el.textContent = message;
    el.className = "status-" + type;
    if (type === "success") {
        setTimeout(function () {
            el.textContent = "";
            el.className = "";
        }, 5000);
    }
}

// ── Main Detect Handler ──────────────────────────────────────────────────────────

async function handleDetect() {
    var btn = document.getElementById("detect-btn");
    var spinner = document.getElementById("spinner");
    var placeholder = document.getElementById("placeholder-message");
    var results = document.getElementById("results");

    btn.disabled = true;
    spinner.classList.remove("hidden");
    placeholder.classList.add("hidden");
    results.classList.add("hidden");
    showDetectStatus("Scanning for orphaned receipts...", "info");

    try {
        var data = await fetchOrphanedReceipts();
        renderOrphanedTable(data.orphaned_receipts);
        renderBrokenTable(data.broken_references);
        results.classList.remove("hidden");

        var total = data.orphaned_receipts.length + data.broken_references.length;
        if (total === 0) {
            showDetectStatus("No issues found", "success");
        } else {
            showDetectStatus(
                data.orphaned_receipts.length + " orphaned, " +
                data.broken_references.length + " broken references",
                "info",
            );
        }
    } catch (err) {
        showDetectStatus("Detection failed: " + err.message, "error");
        placeholder.classList.remove("hidden");
    } finally {
        btn.disabled = false;
        spinner.classList.add("hidden");
    }
}

// ── Init ─────────────────────────────────────────────────────────────────────────

function initOrphanedReceipts() {
    document.getElementById("detect-btn").addEventListener("click", handleDetect);
}
