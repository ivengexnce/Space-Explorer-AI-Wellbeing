<?php
// ============================================================
//  OrbitX Login — FIXED & SECURED
//  Fixes: SQL injection via prepared statements,
//         missing session regeneration, proper redirects
// ============================================================

session_start();

// Already logged in? Redirect straight to dashboard
if (isset($_SESSION['user_id'])) {
    header("Location: ../dashboard/dashboard.html");
    exit();
}

// Only handle POST
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header("Location: login.html");
    exit();
}

// ── DB CONFIG ────────────────────────────────────────────────
$host     = "localhost";
$dbUser   = "root";
$dbPass   = "";
$database = "orbitx_db";

$conn = new mysqli($host, $dbUser, $dbPass, $database);

if ($conn->connect_error) {
    error_log("DB connection failed: " . $conn->connect_error);
    die(json_encode(["error" => "Service temporarily unavailable. Please try again later."]));
}

// ── SANITISE INPUT ───────────────────────────────────────────
$email    = trim($_POST['email']    ?? '');
$password = trim($_POST['password'] ?? '');

if (empty($email) || empty($password)) {
    redirectWithError("Please enter both email and password.");
}

if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    redirectWithError("Invalid email address.");
}

// ── PREPARED STATEMENT (fixes SQL injection) ─────────────────
$stmt = $conn->prepare("SELECT id, username, password FROM users WHERE email = ? LIMIT 1");

if (!$stmt) {
    error_log("Prepare failed: " . $conn->error);
    redirectWithError("Server error. Please try again.");
}

$stmt->bind_param("s", $email);
$stmt->execute();
$result = $stmt->get_result();

if ($result->num_rows === 0) {
    redirectWithError("No account found with that email.");
}

$user = $result->fetch_assoc();
$stmt->close();
$conn->close();

// ── VERIFY PASSWORD ──────────────────────────────────────────
if (!password_verify($password, $user['password'])) {
    redirectWithError("Incorrect password. Please try again.");
}

// ── SESSION — regenerate ID to prevent fixation attacks ──────
session_regenerate_id(true);

$_SESSION['user_id']  = $user['id'];
$_SESSION['username'] = $user['username'];
$_SESSION['email']    = $email;
$_SESSION['logged_in_at'] = time();

// ── REDIRECT ─────────────────────────────────────────────────
header("Location: ../dashboard/dashboard.html");
exit();

// ── HELPER ───────────────────────────────────────────────────
function redirectWithError(string $msg): never {
    $encoded = urlencode($msg);
    header("Location: login.html?error=$encoded");
    exit();
}
?>