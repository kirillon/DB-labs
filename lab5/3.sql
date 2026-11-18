SET search_path TO "goida-airlines";
WITH delays AS (
    SELECT
        f.*,
        EXTRACT(
            EPOCH FROM actual_departure - planned_departure
        ) / 60.0 AS delay_minutes
    FROM Flight f
    WHERE status <> 'отменен'
      AND actual_departure IS NOT NULL
),
metrics AS (
    SELECT
        d.*,
        COALESCE(AVG(delay_minutes) OVER previous_five,0) AS previous_five_average,
        COALESCE(AVG(delay_minutes) OVER current_six) AS current_six_average,
        MAX(delay_minutes) OVER current_six AS current_six_maximum,
        COUNT(*) FILTER (
            WHERE delay_minutes > 15
        ) OVER current_six AS delayed_flight_count,
        AVG(delay_minutes) OVER cumulative AS cumulative_average
    FROM delays d
    WINDOW
        route AS (
            PARTITION BY departure_airport_id, arrival_airport_id
            ORDER BY flight_date, planned_departure
        ),
        previous_five AS (
            route
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ),
        current_six AS (
            route
            ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
        ),
        cumulative AS (
            route
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
)
SELECT
    departure.name AS departure_airport,
    arrival.name AS arrival_airport,
    m.flight_number,
    m.flight_date,
    m.planned_departure,
    m.delay_minutes,
    m.previous_five_average,
    m.current_six_average,
    m.current_six_maximum,
    m.delayed_flight_count,
    m.cumulative_average,
    COALESCE(m.delay_minutes - m.previous_five_average,0) AS deviation_delts
FROM metrics m
JOIN Airport departure ON departure.id = m.departure_airport_id
JOIN Airport arrival ON arrival.id = m.arrival_airport_id
ORDER BY
    departure.name, arrival.name,
    m.flight_date, m.planned_departure;
