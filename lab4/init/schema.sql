CREATE SCHEMA IF NOT EXISTS "goida-airlines";
SET search_path TO "goida-airlines";
CREATE TYPE airplane_status AS ENUM ('исправно', 'на тех обслуживании','ожидает тех обслуживания','утилизирован');
CREATE TYPE approval_status AS ENUM ('на утверждении', 'принята', 'архив');
CREATE TYPE service_class AS ENUM ('эконом', 'бизнес', 'первый класс');
CREATE TYPE flight_status AS ENUM ('прибыл', 'вылетел', 'запланирован', 'в воздухе', 'отменен', 'задержан');
CREATE TYPE employee_status AS ENUM ('действующий', 'уволен', 'на больничном', 'в отпуске');
CREATE TYPE booking_status AS ENUM ('в процессе оплаты', 'оплачено', 'отмена');
CREATE TYPE ticket_status AS ENUM ('отменен', 'действителен','истек');
CREATE TYPE baggage_status AS ENUM ('зарегистрирован', 'сортировка', 'загружен', 'в пути', 'готов к выдаче');
CREATE TYPE baggage_event_type AS ENUM ('приём', 'погрузка', 'перегрузка', 'прибытие', 'выдача');
CREATE TYPE weekday AS ENUM ('понедельник', 'вторник', 'среда', 'четверг', 'пятница','суббота','воскресенье');
CREATE TYPE currency_type AS ENUM ('доллар', 'евро', 'юань', 'рубль', 'йены','тенге','лиры');
CREATE TYPE work_type AS ENUM ( 'осмотр', 'техническое обслуживание', 'ремонт','замена детали','заправка');
CREATE TYPE work_status AS ENUM (  'запланирована','выполняется', 'завершена','отменена');
CREATE TYPE incident_type AS ENUM ( 'техническая неисправность','повреждение самолета','авиационное происшествие','крушение','отмена рейса');
CREATE TYPE incident_status AS ENUM ('зарегистрирован','расследуется', 'закрыт');
CREATE TYPE gender_type AS ENUM ( 'мужской','женский','другое');
CREATE TYPE crew_position AS ENUM ('командир воздушного судна','второй пилот','старший бортпроводник','бортпроводник');
CREATE TYPE fare_type AS ENUM ( 'стандартный','расширенный','все включено');

CREATE TABLE Airport (
    id SERIAL PRIMARY KEY,
    code CHAR(3) NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    CONSTRAINT chk_arprt_code CHECK ( code ~ '[A-Z]{3}$')
);

CREATE TABLE AirplaneType (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    manufacturer TEXT NOT NULL,
    capacity INTEGER  NOT NULL CHECK (capacity > 0),
    velocity NUMERIC(10,2)  NOT NULL CHECK (velocity > 0),
    height INTEGER  NOT NULL CHECK (height > 0),
    range NUMERIC(10,2)  NOT NULL CHECK (range > 0),
    weight NUMERIC(10,2)  NOT NULL CHECK (weight > 0),
    wingspan NUMERIC(10,2)  NOT NULL CHECK (wingspan > 0)
);

CREATE TABLE Airplane (
    id SERIAL PRIMARY KEY,
    type_id INTEGER  NOT NULL REFERENCES AirplaneType(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    registration_number CHAR(7) NOT NULL UNIQUE,
    entry_date DATE  NOT NULL,
    status airplane_status  NOT NULL
);

CREATE TABLE CabinScheme (
    id SERIAL PRIMARY KEY,
    type_id INTEGER NOT NULL REFERENCES AirplaneType(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    valid_from DATE  NOT NULL,
    status approval_status  NOT NULL,
    CONSTRAINT cabin_scheme_version UNIQUE (type_id, version_number)
);

CREATE TABLE Seat (
    scheme_id INTEGER  NOT NULL REFERENCES CabinScheme(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    seat_number TEXT  NOT NULL,
    service_class service_class  NOT NULL,
    emergency_exit BOOLEAN  NOT NULL,
    CONSTRAINT pk_seat PRIMARY KEY (scheme_id, seat_number)
);

CREATE TABLE Schedule (
    id SERIAL PRIMARY KEY,
    departure_airport_id INTEGER  NOT NULL REFERENCES Airport(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    arrival_airport_id INTEGER  NOT NULL REFERENCES Airport(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    valid_from DATE  NOT NULL,
    valid_to DATE  NOT NULL,
    operating_days weekday[]  NOT NULL,
    departure_time TIME  NOT NULL,
    arrival_time TIME  NOT NULL,
    shift_days INTEGER  NOT NULL,
    status approval_status  NOT NULL
);

CREATE TABLE Flight (
    id SERIAL PRIMARY KEY,
    schedule_id INTEGER  NOT NULL REFERENCES Schedule(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    departure_airport_id INTEGER  NOT NULL REFERENCES Airport(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    arrival_airport_id INTEGER  NOT NULL REFERENCES Airport(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    airplane_id INTEGER  NOT NULL REFERENCES Airplane(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    flight_number INTEGER NOT NULL CHECK (flight_number > 0),
    flight_date DATE NOT NULL,
    planned_departure TIMESTAMP  NOT NULL,
    planned_arrival TIMESTAMP  NOT NULL,
    actual_departure TIMESTAMP ,
    actual_arrival TIMESTAMP  ,
    status flight_status  NOT NULL,
    previous_airplane_id INTEGER  REFERENCES Airplane(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT uq_flight_number_date UNIQUE (flight_number, flight_date)
);

CREATE TABLE CrewMember (
    id SERIAL PRIMARY KEY,
    person_number INTEGER NOT NULL UNIQUE CHECK (person_number > 0),
    full_name TEXT  NOT NULL,
    position crew_position  NOT NULL,
    qualification TEXT  NOT NULL,
    flight_hours NUMERIC(10,2)  NOT NULL CHECK (flight_hours > 0),
    status employee_status  NOT NULL
);

CREATE TABLE CrewPermission (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES CrewMember(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    type_id INTEGER NOT NULL  REFERENCES AirplaneType(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    role crew_position NOT NULL,
    issue_date DATE NOT NULL,
    valid_to DATE NOT NULL,
    basis TEXT NOT NULL,
    status approval_status NOT NULL
);

CREATE TABLE CrewAssignment (
    flight_id INTEGER  NOT NULL REFERENCES Flight(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    employee_id INTEGER NOT NULL  REFERENCES CrewMember(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    role TEXT NOT NULL ,
    responsible TEXT NOT NULL,
    status TEXT NOT NULL,
    CONSTRAINT pk_crew_assignment PRIMARY KEY (flight_id, employee_id)
);

CREATE TABLE Booking (
    id SERIAL NOT NULL PRIMARY KEY,
    code INTEGER NOT NULL UNIQUE CHECK (code > 0),
    customer_name VARCHAR(70) NOT NULL,
    created_at DATE NOT NULL,
    valid_to DATE NOT NULL,

    status booking_status NOT NULL
);

CREATE TABLE Passenger (
    id SERIAL NOT NULL PRIMARY KEY,
    full_name TEXT NOT NULL,
    document_type TEXT NOT NULL,
    document_number TEXT NOT NULL,
    phone TEXT NOT NULL,
    birth_date DATE NOT NULL,
    sex gender_type NOT NULL,
    citizenship TEXT NOT NULL
);

CREATE TABLE Ticket (
    id SERIAL NOT NULL PRIMARY KEY,
    number INTEGER NOT NULL UNIQUE CHECK (number > 0),
    booking_id  INTEGER NOT NULL REFERENCES Booking(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    passenger_id INTEGER NOT NULL REFERENCES Passenger(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    flight_id INTEGER NOT NULL REFERENCES Flight(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    scheme_id INTEGER NOT NULL,
    seat_number TEXT NOT NULL,
    previous_ticket_id INTEGER REFERENCES Ticket(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    fare fare_type NOT NULL,
    cost INTEGER NOT NULL,
    currency currency_type NOT NULL,
    max_baggage_weight NUMERIC(10,2) NOT NULL CHECK (max_baggage_weight >= 0),
    status ticket_status NOT NULL,
    CONSTRAINT fk_ticket_seat FOREIGN KEY (scheme_id, seat_number) REFERENCES Seat(scheme_id, seat_number)
        MATCH FULL ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE TABLE Baggage (
    id SERIAL NOT NULL  PRIMARY KEY,
    ticket_id INTEGER  NOT NULL REFERENCES Ticket(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    tag_number INTEGER NOT NULL UNIQUE CHECK (tag_number > 0),
    weight NUMERIC(10,2) NOT NULL  CHECK (weight > 0),
    length NUMERIC(10,2) NOT NULL CHECK (length > 0),
    width NUMERIC(10,2) NOT NULL CHECK (width > 0),
    height NUMERIC(10,2) NOT NULL CHECK (height > 0),
    status baggage_status
);

CREATE TABLE BaggageEvent (
    baggage_id INTEGER NOT NULL REFERENCES Baggage(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    event_type baggage_event_type NOT NULL,
    event_time TIMESTAMP NOT NULL,
    previous_state baggage_status NOT NULL,
    new_state baggage_status NOT NULL,
    CONSTRAINT pk_baggage_event PRIMARY KEY (baggage_id, event_type)
);

CREATE TABLE Incident (
    id SERIAL NOT NULL PRIMARY KEY,
    airplane_id INTEGER NOT NULL REFERENCES Airplane(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    flight_id INTEGER NOT NULL REFERENCES Flight(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    event_date TIMESTAMP NOT NULL,
    type incident_type NOT NULL,
    description TEXT NOT NULL,
    severity INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 10),
    responsible TEXT NOT NULL,
    status incident_status NOT NULL,
    cost NUMERIC(10,2) NOT NULL
);

CREATE TABLE TechnicalWork (
    id SERIAL  NOT NULL PRIMARY KEY,
    airplane_id INTEGER NOT NULL REFERENCES Airplane(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    incident_id INTEGER  NOT NULL REFERENCES Incident(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    work_type work_type NOT NULL,
    planned_start DATE NOT NULL,
    planned_end DATE NOT NULL,
    actual_start DATE NOT NULL,
    actual_end DATE NOT NULL,
    executor TEXT NOT NULL,
    status work_status NOT NULL
);

CREATE TABLE Layout (
    id SERIAL NOT NULL PRIMARY KEY,
    airplane_id INTEGER NOT NULL REFERENCES Airplane(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    scheme_id INTEGER NOT NULL REFERENCES CabinScheme(id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE TABLE BookingPassengerList(
    id SERIAL NOT NULL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES Booking(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    p_id INTEGER NOT NULL REFERENCES Passenger(id) ON DELETE RESTRICT ON UPDATE CASCADE
);



