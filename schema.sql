-- OpenShelf database schema (Stage 1: Users, Books, Reviews)
-- Later stages will add comments, votes, wishlist and reading status.

CREATE DATABASE IF NOT EXISTS book_review_system
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE book_review_system;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    email VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_username (username),
    UNIQUE KEY unique_email (email)
);

CREATE TABLE IF NOT EXISTS books (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    author VARCHAR(200) NOT NULL,
    genre VARCHAR(80) NOT NULL,
    cover_url VARCHAR(500) NULL,
    cover_filename VARCHAR(255) NULL,
    description TEXT NULL,
    isbn VARCHAR(20) NULL,
    publisher VARCHAR(200) NULL,
    publication_year SMALLINT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_books_title (title),
    INDEX idx_books_author (author),
    INDEX idx_books_genre (genre)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    book_id INT NOT NULL,
    rating DECIMAL(2, 1) NOT NULL,
    review_text TEXT NOT NULL,
    is_spoiler TINYINT(1) NOT NULL DEFAULT 0,
    status ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_user_book_review (user_id, book_id),
    INDEX idx_reviews_book_status (book_id, status),
    CONSTRAINT fk_reviews_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_reviews_book
        FOREIGN KEY (book_id) REFERENCES books(id)
        ON DELETE CASCADE,
    CONSTRAINT chk_review_rating_range
        CHECK (rating >= 1.0 AND rating <= 5.0),
    CONSTRAINT chk_review_rating_step
        CHECK (rating * 2 = FLOOR(rating * 2))
);
