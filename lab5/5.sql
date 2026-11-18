SET search_path TO "goida-airlines";
WITH flight_stats AS (
    SELECT
        airplane_id,
        COUNT(*) AS flight_count,
        SUM(
            EXTRACT(EPOCH FROM actual_arrival - actual_departure)
            / 3600.0
        ) AS flight_hours
    FROM Flight
    WHERE status <> 'отменен'
    GROUP BY airplane_id
),
incident_stats AS (
    SELECT
        airplane_id,
        COUNT(*) AS incident_count,
        AVG(severity) AS average_severity,
        MAX(severity) AS maximum_severity,
        SUM(cost) AS incident_cost
    FROM Incident
    GROUP BY airplane_id
),
work_stats AS (
    SELECT
        airplane_id,
        COUNT(*) AS work_count,
        COUNT(*) FILTER (
            WHERE work_type = 'ремонт'
        ) AS repair_count,
        SUM(actual_end - actual_start) FILTER (
            WHERE status = 'завершена'
        ) AS downtime_days
    FROM TechnicalWork
    WHERE status <> 'отменена'
    GROUP BY airplane_id
),
replacement_stats AS (
    SELECT
        previous_airplane_id AS airplane_id,
        COUNT(*) AS replacement_count
    FROM Flight
    WHERE previous_airplane_id IS NOT NULL
    GROUP BY previous_airplane_id
),
metrics AS (
    SELECT
        a.id,
        a.registration_number,
        a.type_id,
        at.name AS airplane_type,
        COALESCE(f.flight_count, 0) AS flight_count,
        COALESCE(f.flight_hours, 0) AS flight_hours,
        COALESCE(i.incident_count, 0) AS incident_count,
        i.average_severity,
        i.maximum_severity,
        COALESCE(i.incident_cost, 0) AS incident_cost,
        COALESCE(w.work_count, 0) AS work_count,
        COALESCE(w.repair_count, 0) AS repair_count,
        COALESCE(w.downtime_days, 0) AS downtime_days,
        COALESCE(r.replacement_count, 0) AS replacement_count,
        COALESCE(i.incident_count, 0) * 100.0
            / f.flight_count AS incidents_per_100_flights,
        COALESCE(w.downtime_days, 0) * 100.0
            / f.flight_count AS downtime_per_100_flights
    FROM Airplane a
    JOIN AirplaneType at ON at.id = a.type_id
    LEFT JOIN flight_stats f ON f.airplane_id = a.id
    LEFT JOIN incident_stats i ON i.airplane_id = a.id
    LEFT JOIN work_stats w ON w.airplane_id = a.id
    LEFT JOIN replacement_stats r ON r.airplane_id = a.id
)
SELECT
    m.*,
    DENSE_RANK() OVER (
        PARTITION BY type_id
        ORDER BY
            incidents_per_100_flights,
            downtime_days,
            replacement_count, 
            flight_count DESC
    ) AS type_rank,
    DENSE_RANK() OVER (
        ORDER BY
            incidents_per_100_flights,
            average_severity,
            downtime_days,
            flight_count DESC
    ) AS fleet_rank
FROM metrics m
ORDER BY fleet_rank, registration_number;
