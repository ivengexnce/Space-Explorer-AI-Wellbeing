<?php

$host = "localhost";
$user = "root";
$password = "";
$database = "orbitx_db";

$conn = new mysqli($host,$user,$password,$database);

if($conn->connect_error){
    die("Database connection failed");
}

/* Get form data */

$username = $_POST['username'];
$fullName = $_POST['fullName'];
$email = $_POST['email'];
$phone = $_POST['phone'];
$password = $_POST['password'];

/* Secure password */

$hashedPassword = password_hash($password, PASSWORD_DEFAULT);

/* Check if user already exists */

$check = "SELECT * FROM users WHERE email='$email' OR username='$username'";
$result = $conn->query($check);

if($result->num_rows > 0){

    echo "❌ User already exists";

}
else{

    $sql = "INSERT INTO users (username, fullName, email, phone, password)
            VALUES ('$username','$fullName','$email','$phone','$hashedPassword')";

    if($conn->query($sql) === TRUE){

        header("Location: ../auth/login.html");
        exit();

    }
    else{

        echo "❌ Error creating account";

    }

}

$conn->close();

?>