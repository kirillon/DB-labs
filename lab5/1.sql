SET search_path TO "goida-airlines";

WITH ticket_stats AS (
    SELECT
        flight_id,
        COUNT(*) AS ticket_count,
        COUNT(DISTINCT passenger_id) AS passenger_count,
        SUM(cost) AS revenue
    FROM Ticket
    WHERE status = 'действителен'
    GROUP BY flight_id
),
baggage_stats AS (
    SELECT
        t.flight_id,
        COUNT(*) AS baggage_count,
        SUM(b.weight) AS baggage_weight
    FROM Ticket t
    JOIN Baggage b ON b.ticket_id = t.id
    WHERE t.status = 'действителен'
    GROUP BY t.flight_id
),
flight_stats AS (
    SELECT
        f.departure_airport_id,
        f.arrival_airport_id,
        COALESCE(t.passenger_count, 0) AS passenger_count,
        COALESCE(t.revenue, 0) AS revenue,
        COALESCE(b.baggage_count, 0) AS baggage_count,
        COALESCE(b.baggage_weight, 0) AS baggage_weight,
        COALESCE(t.ticket_count, 0) * 100.0
            / at.capacity AS load_percent,
        EXTRACT(
            EPOCH FROM f.actual_departure - f.planned_departure
        ) / 60.0 AS delay_minutes
    FROM Flight f
    JOIN Airplane a ON a.id = f.airplane_id
    JOIN AirplaneType at ON at.id = a.type_id
    LEFT JOIN ticket_stats t ON t.flight_id = f.id
    LEFT JOIN baggage_stats b ON b.flight_id = f.id
    WHERE f.status <> 'отменен'
)
SELECT
    departure.name AS departure_airport,
    arrival.name AS arrival_airport,
    COUNT(*) AS flight_count,
    SUM(fs.passenger_count) AS passenger_count,
    SUM(fs.revenue) AS total_revenue,
    AVG(fs.revenue) AS average_revenue,
    AVG(fs.load_percent) AS average_load_percent,
    AVG(fs.delay_minutes) AS average_delay_minutes,
    SUM(fs.baggage_count) AS baggage_count,
    SUM(fs.baggage_weight) AS baggage_weight
FROM flight_stats fs
JOIN Airport departure ON departure.id = fs.departure_airport_id
JOIN Airport arrival ON arrival.id = fs.arrival_airport_id
GROUP BY
    departure.id, arrival.id
HAVING COUNT(*) >= 1
   AND AVG(fs.load_percent) >= 5
ORDER BY AVG(fs.load_percent) DESC, SUM(fs.revenue) DESC;
