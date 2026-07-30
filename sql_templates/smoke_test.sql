CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
    id       BIGINT AUTO_INCREMENT PRIMARY KEY,
    name     VARCHAR(200),
    value    DOUBLE,
    date     DATE,
    status   VARCHAR(50),
    score    INT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_date (date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
