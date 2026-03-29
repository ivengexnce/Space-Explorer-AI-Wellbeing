/* ===============================
   ELEMENTS
================================ */
const profileBtn = document.getElementById("profileBtn");
const dropdown = document.getElementById("dropdown");
const themeToggle = document.getElementById("themeToggle");
const themeToggle2 = document.getElementById("themeToggle2");
const editProfileBtn = document.getElementById("editProfileBtn");
const modal = document.getElementById("editModal");
const editName = document.getElementById("editName");
const editEmail = document.getElementById("editEmail");
const editAvatar = document.getElementById("editAvatar");
const editBio = document.getElementById("editBio");
const editPhone = document.getElementById("editPhone");
const saveProfile = document.getElementById("saveProfile");
const cancelEdit = document.getElementById("cancelEdit");
const cancelEditBtn = document.getElementById("cancelEditBtn");
const profileName = document.getElementById("profileName");
const profileEmail = document.getElementById("profileEmail");
const profileAvatar = document.getElementById("profileAvatar");
const dropdownName = document.getElementById("dropdownName");
const dropdownEmail = document.getElementById("dropdownEmail");
const dropdownAvatar = document.getElementById("dropdownAvatar");
const avatarPreview = document.getElementById("avatarPreview");
const navButtons = document.querySelectorAll(".nav-btn[data-page]");
const pages = document.querySelectorAll(".page");
const toast = document.getElementById("toast");
const globalSearch = document.getElementById("globalSearch");
const logoutBtn = document.getElementById("logoutBtn");
const logoutDropBtn = document.getElementById("logoutDropBtn");
const settingsDropBtn = document.getElementById("settingsDropBtn");
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebar = document.getElementById("sidebar");

/* ===============================
   TOAST HELPER
================================ */
function showToast(msg, type = "") {
    toast.textContent = msg;
    toast.className = "toast show" + (type ? " " + type : "");
    setTimeout(() => toast.className = "toast", 3000);
}

/* ===============================
   CURRENT DATE
================================ */
const dateEl = document.getElementById("currentDate");
if (dateEl) {
    const now = new Date();
    dateEl.textContent = now.toLocaleDateString("en-US", {
        weekday: "short",
        year: "numeric",
        month: "short",
        day: "numeric"
    });
}

/* ===============================
   SIDEBAR TOGGLE
================================ */
sidebarToggle && sidebarToggle.addEventListener("click", () => {
    sidebar.classList.toggle("collapsed");
});

/* ===============================
   PROFILE — LOAD FROM STORAGE
================================ */
function loadProfile() {
    const name = localStorage.getItem("name") || "Explorer";
    const email = localStorage.getItem("email") || "user@orbitx.space";
    const avatar = localStorage.getItem("avatar") || "https://i.pravatar.cc/40";

    profileName.textContent = name;
    profileEmail.textContent = email;
    dropdownName.textContent = name;
    dropdownEmail.textContent = email;

    // Set all avatar images
    [profileAvatar, dropdownAvatar].forEach(el => { if (el) el.src = avatar; });
    if (avatarPreview) avatarPreview.src = avatar.replace("/40", "/80");
}
loadProfile();

/* ===============================
   DROPDOWN
================================ */
profileBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown.classList.toggle("show");
    profileBtn.classList.toggle("open");
});

document.addEventListener("click", (e) => {
    if (!profileBtn.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.classList.remove("show");
        profileBtn.classList.remove("open");
    }
});

/* ===============================
   ESC KEY HANDLING
================================ */
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        dropdown.classList.remove("show");
        profileBtn.classList.remove("open");
        closeModal();
    }
});

/* ===============================
   DARK MODE
================================ */
function applyTheme(dark) {
    document.body.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "true" : "false");
    if (themeToggle) themeToggle.checked = dark;
    if (themeToggle2) themeToggle2.checked = dark;
    // Update charts if they exist
    if (window.missionChartInstance) updateChartTheme(window.missionChartInstance);
    if (window.agencyChartInstance) updateChartTheme(window.agencyChartInstance);
    if (window.launchChartInstance) updateChartTheme(window.launchChartInstance);
}

function updateChartTheme(chart) {
    const isDark = document.body.classList.contains("dark");
    const gridColor = isDark ? "rgba(255,255,255,.07)" : "rgba(0,0,0,.06)";
    const textColor = isDark ? "#94a3b8" : "#64748b";
    if (chart.options.scales && chart.options.scales.y) {
        chart.options.scales.y.grid.color = gridColor;
        chart.options.scales.y.ticks.color = textColor;
    }
    if (chart.options.scales && chart.options.scales.x) {
        chart.options.scales.x.ticks.color = textColor;
    }
    chart.update();
}

themeToggle && themeToggle.addEventListener("change", () => applyTheme(themeToggle.checked));
themeToggle2 && themeToggle2.addEventListener("change", () => applyTheme(themeToggle2.checked));

// Sync settings dark toggle with dropdown dark toggle
const compactToggle = document.getElementById("compactToggle");
compactToggle && compactToggle.addEventListener("change", () => {
    document.body.classList.toggle("compact", compactToggle.checked);
});

// Load saved theme
applyTheme(localStorage.getItem("theme") === "true");

/* ===============================
   PAGE SWITCHING
================================ */
function switchPage(pageID, button) {
    navButtons.forEach(btn => btn.classList.remove("active"));

    // Also clear active from the Home anchor
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));

    if (button) button.classList.add("active");

    pages.forEach(p => p.classList.remove("active"));

    const page = document.getElementById(pageID);
    if (page) page.classList.add("active");

    // Init charts lazily when their page becomes active
    if (pageID === "dashboard" && !window.missionChartInstance) initDashboardCharts();
    if (pageID === "analytics" && !window.launchChartInstance) initAnalyticsChart();
}

navButtons.forEach(btn => {
    btn.addEventListener("click", () => {
        const page = btn.dataset.page;
        if (!page) return;
        switchPage(page, btn);
    });
});

// Settings link from dropdown
settingsDropBtn && settingsDropBtn.addEventListener("click", () => {
    const btn = document.querySelector('[data-page="settings"]');
    if (btn) { switchPage("settings", btn); }
    dropdown.classList.remove("show");
});

/* ===============================
   KEYBOARD NAVIGATION (1-9)
================================ */
document.addEventListener("keydown", (e) => {
    if (document.activeElement.tagName === "INPUT" ||
        document.activeElement.tagName === "TEXTAREA") return;

    const num = parseInt(e.key);
    if (num >= 1 && num <= navButtons.length) {
        navButtons[num - 1].click();
    }
});

/* ===============================
   GLOBAL SEARCH
================================ */
globalSearch && globalSearch.addEventListener("input", () => {
    const q = globalSearch.value.toLowerCase().trim();
    if (!q) return;
    // Simple: find a page whose title or content matches
    pages.forEach(p => {
        if (p.textContent.toLowerCase().includes(q)) {
            const id = p.id;
            const btn = document.querySelector(`[data-page="${id}"]`);
            if (btn) { switchPage(id, btn); }
        }
    });
});

/* ===============================
   LOGOUT
================================ */
function logout() {
    const confirmLogout = confirm("Are you sure you want to logout?");
    if (!confirmLogout) return;

    localStorage.clear(); // 🔥 better than removing individually

    showToast("Logging out...", "");

    setTimeout(() => {
        window.location.href = "../home/home.html";
    }, 1000);
}

logoutBtn && logoutBtn.addEventListener("click", logout);
logoutDropBtn && logoutDropBtn.addEventListener("click", logout);

/* ===============================
   EDIT PROFILE MODAL
================================ */
function openModal() {
    editName.value = localStorage.getItem("name") || "";
    editEmail.value = localStorage.getItem("email") || "";
    editPhone.value = localStorage.getItem("phone") || "";
    editBio.value = localStorage.getItem("bio") || "";
    const av = localStorage.getItem("avatar") || "";
    editAvatar.value = av;
    if (avatarPreview) avatarPreview.src = av || "https://i.pravatar.cc/80";
    modal.classList.add("show");
    dropdown.classList.remove("show");
    editName.focus();
}

function closeModal() {
    modal.classList.remove("show");
}

editProfileBtn && editProfileBtn.addEventListener("click", openModal);
cancelEdit && cancelEdit.addEventListener("click", closeModal);
cancelEditBtn && cancelEditBtn.addEventListener("click", closeModal);

// Close modal on backdrop click
modal && modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
});

// Live avatar preview
editAvatar && editAvatar.addEventListener("input", () => {
    if (avatarPreview && editAvatar.value) {
        avatarPreview.src = editAvatar.value;
    }
});

saveProfile && saveProfile.addEventListener("click", () => {
    const name = editName.value.trim();
    const email = editEmail.value.trim();
    const phone = editPhone.value.trim();
    const bio = editBio.value.trim();
    const av = editAvatar.value.trim();

    if (!name) { showToast("Name cannot be empty.", "error"); return; }

    localStorage.setItem("name", name);
    localStorage.setItem("email", email);
    localStorage.setItem("phone", phone);
    localStorage.setItem("bio", bio);
    if (av) localStorage.setItem("avatar", av);

    loadProfile();
    closeModal();
    showToast("✅ Profile updated!", "success");
});

/* ===============================
   DELETE ACCOUNT
================================ */
const deleteCheckbox = document.getElementById("deleteaccount");
const deleteBox = document.getElementById("deleteConfirmBox");
const confirmDeleteBtn = document.getElementById("confirmDeleteBtn");

deleteCheckbox && deleteCheckbox.addEventListener("change", () => {
    deleteBox.style.display = deleteCheckbox.checked ? "block" : "none";
});

confirmDeleteBtn && confirmDeleteBtn.addEventListener("click", () => {
    const enteredPw = document.getElementById("deletePassword").value;
    const storedPw = localStorage.getItem("password") || ""; // match actual stored pw

    // For demo: any non-empty password triggers success
    if (enteredPw.length >= 1) {
        document.getElementById("deleteMessage").textContent = "✅ Account Deleted";
        document.getElementById("deleteMessage").style.color = "green";
        localStorage.clear();
        setTimeout(() => { window.location.href = "../home/home.html"; }, 1500);
    } else {
        document.getElementById("deleteMessage").textContent = "❌ Enter your password to confirm";
        document.getElementById("deleteMessage").style.color = "#ef4444";
    }
});

/* ===============================
   CHARTS — DASHBOARD
================================ */
function getChartDefaults() {
    const isDark = document.body.classList.contains("dark");
    return {
        gridColor: isDark ? "rgba(255,255,255,.07)" : "rgba(0,0,0,.06)",
        textColor: isDark ? "#94a3b8" : "#64748b"
    };
}

function initDashboardCharts() {
    const { gridColor, textColor } = getChartDefaults();

    // Line chart
    const ctx1 = document.getElementById("missionChart");
    if (ctx1) {
        window.missionChartInstance = new Chart(ctx1, {
            type: "line",
            data: {
                labels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
                datasets: [{
                    label: "Data Collected (TB)",
                    data: [12, 19, 25, 30, 42, 50],
                    borderColor: "#ff6b2c",
                    backgroundColor: "rgba(255,107,44,.1)",
                    fill: true,
                    tension: .4,
                    pointBackgroundColor: "#ff6b2c",
                    pointRadius: 5,
                    pointHoverRadius: 7
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: gridColor }, ticks: { color: textColor }, beginAtZero: true },
                    x: { grid: { display: false }, ticks: { color: textColor } }
                }
            }
        });
    }

    // Doughnut chart
    const ctx2 = document.getElementById("agencyChart");
    if (ctx2) {
        window.agencyChartInstance = new Chart(ctx2, {
            type: "doughnut",
            data: {
                labels: ["NASA", "ESA", "ISRO", "SpaceX", "JAXA"],
                datasets: [{
                    data: [35, 22, 18, 15, 10],
                    backgroundColor: ["#ff6b2c", "#3b82f6", "#10b981", "#8b5cf6", "#f59e0b"],
                    borderWidth: 2,
                    borderColor: document.body.classList.contains("dark") ? "#1e2535" : "#fff"
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { color: textColor, padding: 16, font: { size: 12 } }
                    }
                },
                cutout: "65%"
            }
        });
    }
}

function initAnalyticsChart() {
    const { gridColor, textColor } = getChartDefaults();
    const ctx = document.getElementById("launchChart");
    if (ctx) {
        window.launchChartInstance = new Chart(ctx, {
            type: "bar",
            data: {
                labels: ["2020", "2021", "2022", "2023", "2024", "2025", "2026"],
                datasets: [{
                        label: "Successful",
                        data: [6, 8, 9, 11, 10, 12, 4],
                        backgroundColor: "#10b981",
                        borderRadius: 6
                    },
                    {
                        label: "Failed",
                        data: [1, 0, 1, 0, 1, 0, 0],
                        backgroundColor: "#ef4444",
                        borderRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        labels: { color: textColor, font: { size: 12 } }
                    }
                },
                scales: {
                    y: { grid: { color: gridColor }, ticks: { color: textColor }, beginAtZero: true },
                    x: { grid: { display: false }, ticks: { color: textColor } }
                }
            }
        });
    }
}

// Init dashboard charts on load since it's the default page
document.addEventListener("DOMContentLoaded", () => {
    initDashboardCharts();
});
// ===== LOAD PROFILE =====
async function loadProfile() {
    try {
        const res = await fetch("http://localhost/OrbitX/dashboard/getProfile.php");

        if (!res.ok) {
            console.error("HTTP error:", res.status);
            return;
        }

        const data = await res.json();
        console.log("DATA:", data);

        if (data.error) return;

        const avatar = data.avatar || "https://i.pravatar.cc/150";

        // Safe DOM updates
        const profileName = document.getElementById("profileName");
        const profileEmail = document.getElementById("profileEmail");
        const profileAvatar = document.getElementById("profileAvatar");

        const dropdownName = document.getElementById("dropdownName");
        const dropdownEmail = document.getElementById("dropdownEmail");
        const dropdownAvatar = document.getElementById("dropdownAvatar");

        if (profileName) profileName.innerText = data.name;
        if (profileEmail) profileEmail.innerText = data.email;
        if (profileAvatar) profileAvatar.src = avatar;

        if (dropdownName) dropdownName.innerText = data.name;
        if (dropdownEmail) dropdownEmail.innerText = data.email;
        if (dropdownAvatar) dropdownAvatar.src = avatar;

    } catch (err) {
        console.error("Error loading profile:", err);
    }
}

loadProfile();


// ===== LOAD EDIT PROFILE =====
// ===== SAFE BLOCK (REPLACE BROKEN AREA) =====

async function loadEditProfile() {
    try {
        const res = await fetch("http://localhost/OrbitX/dashboard/getProfile.php");
        const data = await res.json();

        document.getElementById("editName").value = data.name || "";
        document.getElementById("editEmail").value = data.email || "";
        document.getElementById("editBio").value = data.bio || "";
        document.getElementById("dateOfBirth").value = data.dob || "";

    } catch (err) {
        console.error(err);
    }
}

document.getElementById("editProfileBtn").addEventListener("click", () => {
    document.getElementById("editModal").style.display = "flex";
    loadEditProfile();
});