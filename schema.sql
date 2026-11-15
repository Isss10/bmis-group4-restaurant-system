-- Restaurant reservation system schema
-- Member8 Nov task: database layer, transaction + optimistic locking

-- Customer table
CREATE TABLE customers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(50) NOT NULL,
    phone VARCHAR(20),
    email VARCHAR(50)
);

-- Table table with optimistic lock version
CREATE TABLE restaurant_tables (
    id INT PRIMARY KEY AUTO_INCREMENT,
    table_number VARCHAR(20) NOT NULL UNIQUE,
    capacity INT NOT NULL,
    status ENUM('available', 'reserved') DEFAULT 'available',
    version INT NOT NULL DEFAULT 1
);

-- Booking table
CREATE TABLE bookings (
    id INT PRIMARY KEY AUTO_INCREMENT,
    customer_id INT NOT NULL,
    table_id INT NOT NULL,
    booking_datetime DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (table_id) REFERENCES restaurant_tables(id),
    UNIQUE KEY uk_table_time (table_id, booking_datetime)
);

-- Dish table
CREATE TABLE dishes (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    available BOOLEAN DEFAULT TRUE
);

-- Order table
CREATE TABLE orders (
    id INT PRIMARY KEY AUTO_INCREMENT,
    customer_id INT NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    order_status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

-- Order item table
CREATE TABLE order_items (
    id INT PRIMARY KEY AUTO_INCREMENT,
    order_id INT NOT NULL,
    dish_id INT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (dish_id) REFERENCES dishes(id)
);

-- =============================================
-- Booking transaction example (optimistic locking)
-- This runs at runtime to avoid double booking
-- =============================================
BEGIN;

-- Read current table status and version
SELECT id, status, version
FROM restaurant_tables
WHERE id = ?;

-- Update only when version unchanged and table is available
UPDATE restaurant_tables
SET status = 'reserved', version = version + 1
WHERE id = ?
AND status = 'available'
AND version = ?;

-- Insert booking record only if the update succeeds
INSERT INTO bookings (customer_id, table_id, booking_datetime)
VALUES (?, ?, ?);

COMMIT;

-- If conflict occurs, use: ROLLBACK;
