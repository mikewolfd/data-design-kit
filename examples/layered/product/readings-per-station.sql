SELECT s.station_code, COUNT(r.reading_id) AS reading_count
FROM stations AS s
LEFT JOIN readings AS r ON r.station_code = s.station_code
GROUP BY s.station_code
