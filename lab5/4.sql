SET search_path TO "goida-airlines";
WITH ticket_stats AS (
    SELECT
        flight_id,
        COUNT(*) AS passenger_count
    FROM Ticket
    WHERE status = 'действителен'
    GROUP BY flight_id
),
loads AS (
    SELECT
        f.id,
        f.flight_number,
        f.flight_date,
        f.planned_departure,
        f.departure_airport_id,
        f.arrival_airport_id,
        COALESCE(t.passenger_count, 0) AS passenger_count,
        at.capacity,
        COALESCE(t.passenger_count, 0) * 100.0
            / at.capacity AS load_percent
    FROM Flight f
    JOIN Airplane a ON a.id = f.airplane_id
    JOIN AirplaneType at ON at.id = a.type_id
    LEFT JOIN ticket_stats t ON t.flight_id = f.id
    WHERE f.status <> 'отменен'
),
metrics AS (
    SELECT
        l.*,
        LAG(load_percent) OVER route AS previous_load,
        LAG(load_percent, 2) OVER route AS two_flights_ago_load,
        LAG(passenger_count) OVER route AS previous_passenger_count,
        AVG(load_percent) OVER (
            route ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS average_five_load
    FROM loads l
    WINDOW route AS (
        PARTITION BY departure_airport_id, arrival_airport_id
        ORDER BY flight_date, planned_departure
    )
)
SELECT
    departure.name AS departure_airport,
    arrival.name AS arrival_airport,
    m.flight_number,
    m.flight_date,
    m.planned_departure,
    m.passenger_count,
    m.capacity,
    m.load_percent,
    m.previous_load,
    m.two_flights_ago_load,
    m.previous_passenger_count,
    m.load_percent - m.previous_load,
    m.passenger_count - m.previous_passenger_count AS passenger_change,
    m.average_five_load,
    CASE
        WHEN m.previous_load IS NULL
            THEN 'нет предыдущего рейса'
        WHEN m.load_percent - m.previous_load >= 20
            THEN 'резкий рост'
        WHEN m.load_percent - m.previous_load <= -20
            THEN 'резкое падение'
        WHEN ABS(m.load_percent - m.average_five_load) >= 15
            THEN 'сильное отклонение от среднего'
        ELSE 'стабильно'
    END AS load_dynamics
FROM metrics m
JOIN Airport departure ON departure.id = m.departure_airport_id
JOIN Airport arrival ON arrival.id = m.arrival_airport_id
ORDER BY
    departure.name, arrival.name,
    m.flight_date
