// Receipt upload — select a file, upload to the API, display results.

const ALLOWED_TYPES = {
    "application/pdf": "application/pdf",
    "image/jpeg": "image/jpeg",
    "image/png": "image/png",
    "image/gif": "image/gif",
    "image/webp": "image/webp",
};

// ── API ─────────────────────────────────────────────────────────────────────────

function readFileAsBase64(file) {
    return new Promise(function (resolve, reject) {
        const reader = new FileReader();
        reader.onload = function () {
            // result is "data:<mime>;base64,<data>" — strip the prefix
            const base64 = reader.result.split(",")[1];
            resolve(base64);
        };
        reader.onerror = function () {
            reject(new Error("Failed to read file"));
        };
        reader.readAsDataURL(file);
    });
}

async function uploadReceipt(file, forceStore) {
    const base64Data = await readFileAsBase64(file);
    const contentType = ALLOWED_TYPES[file.type];
    if (!contentType) {
        throw new Error("Unsupported file type: " + file.type);
    }

    const token = await getAccessToken();
    const response = await fetch(CONFIG.apiEndpoint + "/receipt", {
        method: "POST",
        headers: {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            filename: file.name,
            content_type: contentType,
            data: base64Data,
            force_store: forceStore,
        }),
    });

    if (!response.ok) {
        const text = await response.text();
        throw new Error("Upload failed (" + response.status + "): " + text);
    }

    return await response.json();
}

// ── Results Display ─────────────────────────────────────────────────────────────

function displayResults(data) {
    const resultsDiv = document.getElementById("results");
    resultsDiv.innerHTML = "";
    resultsDiv.classList.remove("hidden");

    if (data.entries && data.entries.length > 0) {
        const section = document.createElement("div");
        section.className = "results-section";
        section.innerHTML = "<h2>Extracted Entries</h2>";

        const table = document.createElement("table");
        table.className = "results-table";
        table.innerHTML =
            "<thead><tr>" +
            "<th>Service Date</th><th>Payment Date</th><th>Provider</th>" +
            "<th>Patient</th><th>Category</th><th>Description</th><th>Amount</th>" +
            "</tr></thead>";

        const tbody = document.createElement("tbody");
        for (const entry of data.entries) {
            const tr = document.createElement("tr");
            tr.innerHTML =
                "<td>" + (entry.service_date || "-") + "</td>" +
                "<td>" + (entry.payment_date || "-") + "</td>" +
                "<td>" + escapeHtml(entry.provider || "-") + "</td>" +
                "<td>" + escapeHtml(entry.patient || "-") + "</td>" +
                "<td>" + escapeHtml(entry.category || "-") + "</td>" +
                "<td>" + escapeHtml(entry.description || "-") + "</td>" +
                "<td>" + (entry.amount != null ? "$" + Number(entry.amount).toFixed(2) : "-") + "</td>";
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        section.appendChild(table);
        resultsDiv.appendChild(section);
    }

    if (data.rejections && data.rejections.length > 0) {
        const section = document.createElement("div");
        section.className = "results-section";
        section.innerHTML = "<h2>Rejections</h2>";

        for (const rejection of data.rejections) {
            const card = document.createElement("div");
            card.className = "rejection-card";
            card.innerHTML =
                "<strong>" + escapeHtml(rejection.filename || "Unknown file") + "</strong>" +
                "<p>" + escapeHtml(rejection.description || "") + "</p>" +
                "<p class=\"rejection-reasoning\">" + escapeHtml(rejection.reasoning || "") + "</p>";
            section.appendChild(card);
        }
        resultsDiv.appendChild(section);
    }

    if ((!data.entries || data.entries.length === 0) && (!data.rejections || data.rejections.length === 0)) {
        resultsDiv.innerHTML = "<p class=\"no-results\">No entries or rejections returned.</p>";
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// ── Status ──────────────────────────────────────────────────────────────────────

function showUploadStatus(message, type) {
    const el = document.getElementById("upload-status");
    el.textContent = message;
    el.className = "status-" + type;
    if (type === "success") {
        setTimeout(function () {
            el.textContent = "";
            el.className = "";
        }, 5000);
    }
}

// ── Upload Handler ──────────────────────────────────────────────────────────────

async function handleUpload() {
    const fileInput = document.getElementById("file-input");
    const forceStore = document.getElementById("force-store").checked;
    const file = fileInput.files[0];

    if (!file) {
        showUploadStatus("Please select a file", "error");
        return;
    }

    const btn = document.getElementById("upload-btn");
    const spinner = document.getElementById("spinner");

    btn.disabled = true;
    spinner.classList.remove("hidden");
    document.getElementById("results").classList.add("hidden");
    showUploadStatus("Uploading and analyzing receipt...", "info");

    try {
        const data = await uploadReceipt(file, forceStore);
        displayResults(data);
        showUploadStatus("Analysis complete", "success");
    } catch (err) {
        showUploadStatus("Upload failed: " + err.message, "error");
    } finally {
        btn.disabled = false;
        spinner.classList.add("hidden");
    }
}

// ── Init ────────────────────────────────────────────────────────────────────────

function initUpload() {
    document.getElementById("upload-btn").addEventListener("click", handleUpload);
}
