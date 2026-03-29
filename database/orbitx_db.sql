-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Mar 29, 2026 at 10:36 AM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `orbitx_db`
--

-- --------------------------------------------------------

--
-- Table structure for table `users`
--

CREATE TABLE `users` (
  `id` int(11) NOT NULL,
  `fullName` varchar(100) NOT NULL,
  `username` varchar(100) NOT NULL,
  `email` varchar(100) NOT NULL,
  `phone` varchar(20) DEFAULT NULL,
  `password` varchar(255) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `role` enum('user','admin') DEFAULT 'user',
  `avatar` varchar(255) DEFAULT NULL,
  `bio` text DEFAULT NULL,
  `dob` date DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `users`
--

INSERT INTO `users` (`id`, `fullName`, `username`, `email`, `phone`, `password`, `created_at`, `role`, `avatar`, `bio`, `dob`) VALUES
(1, 'Meet Maru', 'meet', 'meetmaru149@gmail.com', '9967545530', 'meetmaru', '2026-03-12 11:51:28', 'user', NULL, NULL, NULL),
(3, 'chandrabai chawl', 'hememdra_maru', 'neelamaru3@gmail.com', '445643212187843', '$2y$10$Zc63XG1DzPns4bLUFxHeDugDgeT.lzZX1CrlM692IAwR.RLjSV5VC', '2026-03-26 10:52:40', 'user', NULL, NULL, NULL),
(4, 'Meet Maru', 'kuchikumemes', 'meetmaru14900@gmail.com', '09967545530', '$2y$10$XNv/V07MZzu69qRvBfrTsuMOmFPKiHIzIZkDwzP5nGjJNSyj8b3ii', '2026-03-26 11:13:56', 'user', NULL, NULL, NULL),
(5, 'Maseera Sameer Saldulkar', 'maseera21', 'maseera429@gmail.com', '9665199837', '$2y$10$NqbUAPtRcXV1itfO44mAA.qwK7fAE4U2Cb1754LthdWTzBn.9Pxre', '2026-03-27 06:05:27', 'user', NULL, NULL, NULL);

--
-- Indexes for dumped tables
--

--
-- Indexes for table `users`
--
ALTER TABLE `users`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `username` (`username`),
  ADD UNIQUE KEY `email` (`email`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `users`
--
ALTER TABLE `users`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
