SET search_path TO "goida-airlines";
WITH event_stats AS (
    SELECT
        baggage_id,
        COUNT(*) AS event_count,
        MAX(event_time) AS last_event_time
    FROM BaggageEvent
    GROUP BY baggage_id
),
baggage_problems AS (
    SELECT
        b.id AS baggage_id,
        f.flight_date,
        f.flight_number,
        COALESCE(es.event_count, 0) AS event_count,
        es.last_event_time,
        arrival_event.event_time AS arrival_event_time,
        delivery_event.event_time AS delivery_event_time,
        le.last_state,
        le.last_event_type,
        CASE
            WHEN es.baggage_id IS NULL
                THEN 'нет событий багажа'
            WHEN arrival_event.event_time IS NULL
                THEN 'нет события прибытия'
            WHEN delivery_event.event_time IS NULL
                THEN 'багаж не выдан'
            WHEN delivery_event.event_time < f.actual_arrival
                THEN 'выдача зафиксирована до прилета'
            ELSE 'прочая проблема'
        END AS problem_type
    FROM Baggage b
    JOIN Ticket t ON t.id = b.ticket_id
    JOIN Flight f ON f.id = t.flight_id
    LEFT JOIN event_stats es ON es.baggage_id = b.id
    LEFT JOIN BaggageEvent arrival_event
        ON arrival_event.baggage_id = b.id
       AND arrival_event.event_type = 'прибытие'
    LEFT JOIN BaggageEvent delivery_event
        ON delivery_event.baggage_id = b.id
       AND delivery_event.event_type = 'выдача'
    LEFT JOIN (
    SELECT DISTINCT ON (e.baggage_id)
        e.baggage_id,
        e.new_state AS last_state,
        e.event_type AS last_event_type
    FROM BaggageEvent e
    ORDER BY
        e.baggage_id,
        e.event_time DESC,
        e.event_type DESC
) le ON le.baggage_id = b.id
    WHERE f.status = 'прибыл'
      AND f.actual_arrival IS NOT NULL
)
SELECT *
FROM baggage_problems
WHERE problem_type <> 'прочая проблема'
ORDER BY flight_date DESC, flight_number, problem_type;
