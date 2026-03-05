CREATE USER "teleport-admin" login createrole superuser; 

CREATE TABLE sales_records (
    id SERIAL PRIMARY KEY,
    sale_date DATE NOT NULL,
    customer_name VARCHAR(100),
    product VARCHAR(100),
    quantity INTEGER,
    unit_price NUMERIC(10, 2),
    total NUMERIC(10, 2),
    region VARCHAR(50)
);

INSERT INTO sales_records (sale_date, customer_name, product, quantity, unit_price, total, region) VALUES
('2025-05-01', 'Alice Johnson', 'Laptop Pro 14"', 1, 1200.00, 1200.00, 'West Coast'),
('2025-05-02', 'Bob Smith', 'Wireless Mouse', 3, 25.99, 77.97, 'Midwest'),
('2025-05-02', 'Clara Lee', '4K Monitor', 2, 330.00, 660.00, 'East Coast'),
('2025-05-03', 'Daniel Kim', 'USB-C Hub', 5, 45.50, 227.50, 'South'),
('2025-05-04', 'Eva Green', 'Mechanical Keyboard', 1, 89.99, 89.99, 'Midwest'),
('2025-05-05', 'Frank Moore', 'External SSD 1TB', 2, 129.99, 259.98, 'West Coast'),
('2025-05-06', 'Grace Liu', 'Laptop Pro 14"', 1, 1200.00, 1200.00, 'East Coast'),
('2025-05-07', 'Henry White', 'Wireless Earbuds', 4, 59.99, 239.96, 'South'),
('2025-05-07', 'Isla Chan', 'Webcam HD', 3, 75.00, 225.00, 'West Coast'),
('2025-05-08', 'Jack Black', 'Gaming Chair', 1, 299.99, 299.99, 'Midwest');

CREATE USER "read-only" login;
GRANT pg_read_all_data TO "read-only";
GRANT CONNECT ON DATABASE test TO "read-only";
