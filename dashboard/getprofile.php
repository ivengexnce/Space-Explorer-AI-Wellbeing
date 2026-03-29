<?php
header("Content-Type: application/json");

$conn = new mysqli("localhost", "root", "", "orbitx_db");

if ($conn->connect_error) {
    echo json_encode(["error" => "DB failed"]);
    exit;
}

$sql = "SELECT fullName, username, email, avatar, bio, dob FROM users WHERE id = 1";
$result = $conn->query($sql);

if ($result && $row = $result->fetch_assoc()) {
    echo json_encode([
        "name" => $row["fullName"],
        "username" => $row["username"],
        "email" => $row["email"],
        "avatar" => $row["avatar"],
        "bio" => $row["bio"],
        "dob" => $row["dob"]
    ]);
} else {
    echo json_encode(["error" => "No user found"]);
}

$conn->close();
?>