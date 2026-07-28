CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    `U:0`       DOUBLE,
    `U:1`       DOUBLE,
    `U:2`       DOUBLE,
    `alpha.water` DOUBLE,
    p_rgh       DOUBLE,
    vtkValidPointMask TINYINT,
    arc_length  DOUBLE,
    `Points:0`  DOUBLE,
    `Points:1`  DOUBLE,
    `Points:2`  DOUBLE,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
