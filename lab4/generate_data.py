#!/usr/bin/env python3
import argparse
import os
import random
import math
from pathlib import Path
from urllib.request import urlopen
import pycountry
import pandas as pd
import airportsdata
from geopy.distance import geodesic
from openap import prop, aero
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import psycopg
from psycopg import sql
from dotenv import load_dotenv
from faker import Faker

ROLES = ['командир воздушного судна', 'второй пилот',
         'старший бортпроводник', 'бортпроводник', 'бортпроводник', 'бортпроводник']
TABLES = ['airport', 'airplanetype', 'airplane', 'cabinscheme', 'seat',
          'schedule', 'flight', 'crewmember', 'crewpermission', 'crewassignment',
          'booking', 'passenger', 'bookingpassengerlist', 'ticket', 'baggage',
          'baggageevent', 'incident', 'technicalwork', 'layout']



def load_catalogues(rng, country, cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)

    def dataset(name, columns):
        path = cache / name
        if not path.exists():
            url = 'https://raw.githubusercontent.com/jpatokal/openflights/master/data/' + name
            with urlopen(url, timeout=40) as response:
                content = response.read()
            tmp = path.with_suffix('.tmp')
            tmp.write_bytes(content)
            tmp.replace(path)
        return pd.read_csv(path, names=columns, keep_default_na=False, na_values=[r'\N'])

    airports = pd.DataFrame(airportsdata.load('IATA').values())
    airports = airports[(airports.country == country) & airports.iata.str.fullmatch('[A-Z]{3}')]
    airports = airports[(airports.name != '') & (airports.city != '')].drop_duplicates('name')
    if len(airports) < 2:
        raise ValueError('В airportsdata недостаточно аэропортов страны ' + country)
    coordinates = airports.set_index('iata')[['lat', 'lon']].to_dict('index')
    planes = dataset('planes.dat', ['full_name', 'iata_model', 'icao'])
    routes = dataset('routes.dat', ['airline', 'airline_id', 'src', 'src_id',
                                    'dst', 'dst_id', 'codeshare', 'stops', 'equipment'])
    routes = routes[(routes.stops == 0) & routes.src.isin(coordinates) & routes.dst.isin(coordinates)]
    routes['iata_model'] = routes.equipment.fillna('').str.split()
    routes = routes.explode('iata_model').merge(planes, on='iata_model')
    routes['icao'] = routes.icao.fillna('').str.lower()
    routes = routes[['src', 'dst', 'icao']].drop_duplicates()
    reverse = routes.rename(columns={'src': 'dst', 'dst': 'src'})
    routes = routes.merge(reverse, on=['src', 'dst', 'icao'])
    properties, model_rows = {}, []
    for code in prop.available_aircraft():
        ac = prop.aircraft(code)
        if not (80 <= ac.get('pax', {}).get('max', 0) <= 220):
            continue
        if ac.get('engine', {}).get('number') != 2:
            continue
        if not all(ac.get(key) for key in ('mmo', 'ceiling', 'mtow', 'aircraft')):
            continue
        if not all(ac.get('cruise', {}).get(key) for key in ('range', 'mach', 'height')):
            continue
        if not ac.get('wing', {}).get('span') or not ac.get('fuselage', {}).get('width'):
            continue
        capacity = int(ac['pax'].get('high', ac['pax']['max']))
        properties[code] = ac
        model_rows.append(dict(icao=code, name=code.upper(),
                               manufacturer=ac['aircraft'].rsplit(' ', 1)[0],
                               capacity=capacity,
                               velocity=round(aero.mach2tas(ac['mmo'], ac['cruise']['height']) * 3.6, 2),
                               height=int(ac['ceiling']), range=ac['cruise']['range'],
                               weight=round(ac['mtow'] / 1000, 2), wingspan=ac['wing']['span']))
    models = pd.DataFrame(model_rows)
    routes = routes[routes.icao.isin(properties)].copy()
    routes['km'] = [geodesic((coordinates[a]['lat'], coordinates[a]['lon']),
                            (coordinates[b]['lat'], coordinates[b]['lon'])).km
                    for a, b in zip(routes.src, routes.dst)]
    routes = routes[(routes.km >= 200) & (routes.km <= 2000)]
    routes = routes[[distance <= properties[code]['cruise']['range'] * .8
                     for distance, code in zip(routes.km, routes.icao)]]

    hub = routes.groupby('src').dst.nunique().sort_values(ascending=False).index[0]
    routes = routes[routes.src == hub].sort_values(['icao', 'dst'])
    codes = sorted(routes.icao.unique())
    codes = rng.sample(codes, min(3, len(codes)))
    routes = routes[routes.icao.isin(codes)]
    selected = []
    for code in codes:
        candidates = routes[routes.icao == code].to_dict('records')
        selected.extend(rng.sample(candidates, min(21, len(candidates))))
    routes = pd.DataFrame(selected)
    airport_codes = [hub] + sorted(set(airports.iata) - {hub})
    airport_ids = {code: i + 1 for i, code in enumerate(airport_codes)}
    airports = airports.set_index('iata').loc[airport_codes].reset_index()
    models = models.set_index('icao').loc[codes].reset_index()
    model_ids = {code: i + 1 for i, code in enumerate(codes)}
    routes['destination'] = routes.dst.map(airport_ids)
    routes['type_id'] = routes.icao.map(model_ids)
    routes['minutes'] = [int(math.ceil((distance / (aero.mach2tas(properties[code]['cruise']['mach'],
                                                     properties[code]['cruise']['height']) * 3.6) * 60 + 40) / 5) * 5)
                         for distance, code in zip(routes.km, routes.icao)]
    routes['price'] = (2500 + routes.km * 4).round(-2).astype(int)
    models['seats_per_row'] = [4 if properties[code]['fuselage']['width'] < 3.3 else 6 for code in codes]
    return airports, models, routes

def read_schema(conn, schema):
    columns = defaultdict(dict)
    for table, col, nullable, udt_schema, udt_name, element in conn.execute('''
        SELECT c.table_name, c.column_name, c.is_nullable, c.udt_schema,
               c.udt_name, et.typname
        FROM information_schema.columns c
        JOIN pg_namespace n ON n.nspname = c.udt_schema
        JOIN pg_type t ON t.typnamespace = n.oid AND t.typname = c.udt_name
        LEFT JOIN pg_type et ON et.oid = t.typelem
        WHERE c.table_schema = %s ORDER BY c.ordinal_position
    ''', (schema,)):
        columns[table][col] = (nullable == 'YES', udt_schema, udt_name, element)
    enums = {}
    for ns, typ, label in conn.execute('''
        SELECT n.nspname, t.typname, e.enumlabel
        FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
        JOIN pg_namespace n ON n.oid = t.typnamespace ORDER BY e.enumsortorder
    '''):
        enums.setdefault((ns, typ), []).append(label)
    return columns, enums


class Data:
    def __init__(self, columns, enums, seed):
        self.columns, self.enums = columns, enums
        self.rng = random.Random(seed)
        self.fake = Faker('ru_RU')
        self.fake.seed_instance(seed)
        self.rows = defaultdict(list)

    def value(self, table, column, *choices):
        """Выбираем только осмысленный вариант, разрешенный текущим ENUM."""
        info = self.columns[table].get(column)
        allowed = self.enums.get((info[1], info[2])) if info else None
        if not allowed:
            return choices[0]
        for choice in choices:
            if choice in allowed:
                return choice
        raise ValueError(f'{table}.{column}: ENUM не содержит {choices}. Есть: {allowed}')

    def add(self, table, **values):
        cols = self.columns[table]
        unknown = set(values) - set(cols)
        if unknown:
            raise ValueError(f'{table}: в БД нет столбцов {sorted(unknown)}. Сверь текущий DDL.')
        row = dict(values)
        if 'id' in cols and 'id' not in row:
            row['id'] = len(self.rows[table]) + 1
        self.rows[table].append(row)
        return row.get('id')

    def person(self, reference_date):
        female = self.rng.random() < .5
        return dict(full_name=self.fake.name_female() if female else self.fake.name_male(),
                    document_type='паспорт РФ',
                    document_number=f'{self.rng.randint(1000, 9999)} {self.rng.randint(100000, 999999)}',
                    phone=self.fake.numerify('+7 9## ###-##-##'),
                    birth_date=date(reference_date.year - self.rng.randint(18, 75),
                                    self.rng.randint(1, 12), self.rng.randint(1, 28)),
                    sex=self.value('passenger', 'sex', 'женский' if female else 'мужской'),
                    citizenship='Россия')

    def build(self, start, days, planes, now, country="RU", cache=".aviation_cache"):
        airports, models, routes = load_catalogues(self.rng, country, cache)
        types_count = len(models)
        crew_sizes = {}
        r = self.rng
        for airport in airports.to_dict('records'):
            nation = pycountry.countries.get(alpha_2=airport['country'])
            self.add('airport', code=airport['iata'], name=airport['name'],
                     city=airport['city'], country=nation.name if nation else airport['country'])
        seats = {}
        for type_id, model in enumerate(models.to_dict('records'), 1):
            self.add('airplanetype', **{key: model[key] for key in
                     ['name', 'manufacturer', 'capacity', 'velocity', 'height', 'range', 'weight', 'wingspan']})
            self.add('cabinscheme', type_id=type_id, version_number=1,
                     valid_from=start - timedelta(days=365),
                     status=self.value('cabinscheme', 'status', 'принята'))
            letters = 'ABCD' if model['seats_per_row'] == 4 else 'ABCDEF'
            crew_sizes[type_id] = 4 if model['seats_per_row'] == 4 else 6
            seats[type_id] = []
            for j in range(model['capacity']):
                seat = f'{j // len(letters) + 1}{letters[j % len(letters)]}'
                seats[type_id].append(seat)
                self.add('seat', scheme_id=type_id, seat_number=seat,
                         service_class=self.value('seat', 'service_class', 'эконом'),
                         emergency_exit=j // len(letters) + 1 in (12, 13))

        for airplane in range(1, planes + 1):
            typ = (airplane - 1) % types_count + 1
            self.add('airplane', type_id=typ, registration_number=f'RA{73000 + airplane}',
                     entry_date=start - timedelta(days=r.randint(730, 3650)),
                     status=self.value('airplane', 'status', 'исправно'))
            self.add('layout', airplane_id=airplane, scheme_id=typ)
            crew_size = crew_sizes[typ]
            for role in ROLES[:crew_size]:
                employee = self.add('crewmember', person_number=10000 + len(self.rows['crewmember']),
                                    full_name=self.fake.name(),
                                    position=self.value('crewmember', 'position', role),
                                    qualification='Действующий сертификат; ежегодная подготовка',
                                    flight_hours=r.randint(800, 12000),
                                    status=self.value('crewmember', 'status', 'действующий'))
                self.add('crewpermission', employee_id=employee, type_id=typ,
                         role=self.value('crewpermission', 'role', role),
                         issue_date=start - timedelta(days=120),
                         valid_to=start + timedelta(days=days + 240),
                         basis='Подготовка на тип; медицинское заключение; проверка навыков',
                         status=self.value('crewpermission', 'status', 'принята'))

        weekdays = self.enums.get((self.columns['schedule']['operating_days'][1],
                                   self.columns['schedule']['operating_days'][3]))
        weekdays = weekdays or ['понедельник', 'вторник', 'среда', 'четверг',
                                'пятница', 'суббота', 'воскресенье']
        weekday_order = [
    'понедельник', 'вторник', 'среда', 'четверг',
    'пятница', 'суббота', 'воскресенье'
]
        flight_info, available = {}, {}
        canceled_days = {(plane, day) for plane in range(1, planes + 1) for day in range(days)
                         if datetime.combine(start + timedelta(days=day), time(20)) < now
                         and (self.rng.random() < .04 or (plane == 1 and day == 0))}
        for airplane in range(1, planes + 1):
            typ = (airplane - 1) % types_count + 1
            route = r.choice(routes[routes.type_id == typ].to_dict('records'))
            destination, minutes, base_price = route['destination'], route['minutes'], route['price']
            first_day = r.randint(0, min(7, days - 1))
            last_day = r.randint(first_day, days - 1)

            possible_days = sorted({
                (start + timedelta(days=d)).weekday()
                for d in range(first_day, last_day + 1)
            })
            chosen_days = set(r.sample(
                possible_days, r.randint(1, len(possible_days))
            ))

            takeoff = datetime.combine(
                start,
                time(r.randint(0, 23), r.randrange(0, 60, 5))
            )

            turnaround = r.randrange(60, 181, 15)

            times = [
                (
                    1, destination,
                    takeoff,
                    takeoff + timedelta(minutes=minutes)
                ),
                (
                    destination, 1,
                    takeoff + timedelta(minutes=minutes + turnaround),
                    takeoff + timedelta(minutes=2 * minutes + turnaround)
                )
            ]
            before = sum(crew_sizes[(p - 1) % types_count + 1] for p in range(1, airplane))
            members = self.rows['crewmember'][before:before + crew_sizes[typ]]
            for leg, (departure, arrival, dep, arr) in enumerate(times):
                departure_shift = (dep.date() - start).days
                
                operating_days = [
                    weekday_order[i]
                    for i in sorted({
                        (d + departure_shift) % 7 for d in chosen_days
                    })
                ]
                
                schedule = self.add(
                    'schedule',
                    departure_airport_id=departure,
                    arrival_airport_id=arrival,
                    valid_from=start + timedelta(days=first_day + departure_shift),
                    valid_to=start + timedelta(days=last_day + departure_shift),
                    operating_days=operating_days,
                    departure_time=dep.time(),
                    arrival_time=arr.time(),
                    shift_days=(arr.date() - dep.date()).days,
                    status=self.value('schedule', 'status', 'принята')
                )
                
                for day in range(first_day, last_day + 1):
                    departure_date = start + timedelta(days=day)
                
                    if departure_date.weekday() not in chosen_days:
                        continue
                    
                    planned_dep = dep + timedelta(days=day)
                    planned_arr = arr + timedelta(days=day)
                
                    canceled = (airplane, day) in canceled_days
                    delay = (
                          0 if r.random() < 0.75
                            else r.randrange(5, 121, 5)
                    )
                    actual_dep = planned_dep + timedelta(minutes=delay)
                    actual_arr = planned_arr + timedelta(minutes=delay)
                    if canceled:
                        state = 'отменен'
                    elif actual_arr <= now:
                        state = 'прибыл'
                    elif actual_dep <= now:
                        state = 'в воздухе'
                    elif planned_dep <= now:
                        state = 'задержан'
                    else:
                        state = 'запланирован'
                    flight = self.add('flight', schedule_id=schedule,
                                      departure_airport_id=departure, arrival_airport_id=arrival,
                                      airplane_id=airplane, flight_number=1000 + airplane * 2 + leg,
                                      flight_date=planned_dep.date(), planned_departure=planned_dep,
                                      planned_arrival=planned_arr,
                                      actual_departure=actual_dep if actual_dep <= now and not canceled else None,
                                      actual_arrival=actual_arr if actual_arr <= now and not canceled else None,
                                      status=self.value('flight', 'status', state), previous_airplane_id=None)
                    for employee, role in zip(members, ROLES):
                        assigned = 'отменен' if canceled else 'выполнен' if actual_arr <= now else 'назначен'
                        self.add('crewassignment', flight_id=flight, employee_id=employee['id'],
                                 start_date=(planned_dep - timedelta(hours=1)).date(),
                                 end_date=(planned_arr + timedelta(minutes=30)).date(),
                                 role=self.value('crewassignment', 'role', role), responsible=members[0]['full_name'],
                                 status=self.value('crewassignment', 'status', assigned, assigned + 'а'))
                    free = seats[typ].copy()
                    r.shuffle(free)
                    available[flight] = free
                    flight_info[flight] = (typ, base_price, canceled)

        people_count = max(100, planes * days * 8)
        for _ in range(people_count):
            self.add('passenger', **self.person(start))
        document_seen = set()
        for p in self.rows['passenger']:
            while p['document_number'] in document_seen:
                p['document_number'] = f'{r.randint(1000, 9999)} {r.randint(100000, 999999)}'
            document_seen.add(p['document_number'])

        used = defaultdict(set)
        journeys = defaultdict(list)
        flights = {(f['airplane_id'], f['flight_date'], f['departure_airport_id']): f
                   for f in self.rows['flight']}

        def can_travel(person, segments):
            for segment in segments:
                if person['id'] in used[segment['id']]:
                    return False
                begin, end = segment['planned_departure'], segment['planned_arrival'] + timedelta(hours=2)
                if any(begin < old_end and old_begin < end
                       for old_begin, old_end in journeys[person['id']]):
                    return False
            return True

        for f in self.rows['flight']:
            fid = f['id']
            typ, price, flight_canceled = flight_info[fid]
            already = len(seats[typ]) - len(available[fid])
            target = max(0, int(len(seats[typ]) * r.uniform(.55, .88)) - already)
            pool = [person for person in self.rows['passenger'] if can_travel(person, [f])]
            return_pools = {}
            while target > 0:
                segments = [f]
                # Часть броней включает обратный перелет через 2–5 дней.
                return_flight = flights.get((f['airplane_id'], f['flight_date'] + timedelta(days=r.randint(2, 5)),
                                             f['arrival_airport_id']))
                if (not flight_canceled and f['departure_airport_id'] == 1 and r.random() < .25
                        and return_flight and return_flight['status'] != 'отменен'
                        and len(available[return_flight['id']]) >= 4):
                    segments.append(return_flight)
                group_size = min(target, r.randint(1, 4))
                if len(segments) > 1:
                    return_id = segments[1]['id']
                    if return_id not in return_pools:
                        return_pools[return_id] = {person['id'] for person in pool if can_travel(person, [segments[1]])}
                    candidates = [person for person in pool if person['id'] in return_pools[return_id]]
                else:
                    candidates = pool.copy()
                while len(candidates) < group_size:
                    person = self.person(start)
                    person['id'] = self.add('passenger', **person)
                    candidates.append(person)
                    pool.append(person)
                    for ids in return_pools.values():
                        ids.add(person['id'])
                group = r.sample(candidates, group_size)
                selected_ids = {person['id'] for person in group}
                pool = [person for person in pool if person['id'] not in selected_ids]
                unpaid = not flight_canceled and f['planned_departure'] > now + timedelta(days=1) and r.random() < .15
                canceled = flight_canceled or r.random() < .07
                created = now.date() if unpaid else min(now.date(), f['planned_departure'].date() - timedelta(days=r.randint(7, 45)))
                booking = self.add('booking', code=700000 + len(self.rows['booking']),
                                   customer_name=group[0]['full_name'], created_at=created,
                                   valid_to=created + timedelta(days=1) if unpaid or canceled else segments[-1]['flight_date'],
                                   status=self.value('booking', 'status', 'отмена' if canceled else 'в процессе оплаты' if unpaid else 'оплачено'))
                for person in group:
                    link_col = 'p_id' if 'p_id' in self.columns['bookingpassengerlist'] else 'passenger_id'
                    self.add('bookingpassengerlist', booking_id=booking, **{link_col: person['id']})
                    if unpaid and not canceled:
                        continue
                    for segment in segments:
                        sid = segment['id']
                        used[sid].add(person['id'])
                        if not canceled:
                            journeys[person['id']].append((segment['planned_departure'], segment['planned_arrival'] + timedelta(hours=2)))
                        fare = r.choices(['стандартный', 'расширенный', 'все включено'], [65, 25, 10])[0]
                        fare = self.value('ticket', 'fare', fare, 'стандартный', 'базовый')
                        seat = available[sid].pop()
                        factor = {'стандартный': 1, 'расширенный': 1.25, 'все включено': 1.5}.get(fare, 1)
                        cost = int(price * factor * r.uniform(.85, 1.35)) // 100 * 100
                        ticket = self.add('ticket', number=60000000 + len(self.rows['ticket']),
                                          booking_id=booking, passenger_id=person['id'], flight_id=sid,
                                          scheme_id=typ, seat_number=seat, previous_ticket_id=None,
                                                                                    fare=fare, cost=cost,
                                          currency=self.value('ticket', 'currency', 'рубль', 'RUB'),
                                          max_baggage_weight=0 if fare == 'базовый' else 32 if fare == 'все включено' else 23,
                                          status=self.value('ticket', 'status', 'отменен' if canceled else 'действителен'))
                        if not canceled and segment['actual_departure'] and r.random() < .6:
                            self.baggage(ticket, segment, now)
                target -= len(group)

        for f in self.rows['flight']:
            if f['status'] != 'отменен' or f['departure_airport_id'] != 1:
                continue
            incident = self.add('incident', airplane_id=f['airplane_id'], flight_id=f['id'],
                                event_date=f['planned_departure'] - timedelta(minutes=50),
                                type=self.value('incident', 'type', 'техническая неисправность', 'отмена рейса'),
                                description='При предполетном осмотре обнаружена неисправность датчика. '
                                            'Рейс отменен; после замены и проверки борт допущен к эксплуатации.',
                                severity=r.randint(2, 5), responsible='Инженер ' + self.fake.name(),
                                status=self.value('incident', 'status', 'закрыт'), cost=r.randint(200, 900) * 1000)
            self.add('technicalwork', airplane_id=f['airplane_id'], incident_id=incident,
                     work_type=self.value('technicalwork', 'work_type', 'замена детали', 'ремонт'),
                     planned_start=f['flight_date'], planned_end=f['flight_date'],
                     actual_start=f['flight_date'], actual_end=f['flight_date'],
                     executor='Техник ' + self.fake.name(),
                     status=self.value('technicalwork', 'status', 'завершена'))

    def baggage(self, ticket, f, now):
        r = self.rng
        arrived = f['actual_arrival'] is not None
        state = 'готов к выдаче' if arrived else 'в пути'
        bid = self.add('baggage', ticket_id=ticket, tag_number=90000000 + len(self.rows['baggage']),
                       weight=Decimal(r.randint(80, 220)) / 10, length=65, width=42, height=25,
                       status=self.value('baggage', 'status', state))
        steps = [('приём', f['planned_departure'] - timedelta(hours=2), 'зарегистрирован'),
                 ('погрузка', f['actual_departure'] - timedelta(minutes=35), 'загружен')]
        if arrived:
            steps.append(('прибытие', f['actual_arrival'] + timedelta(minutes=15), 'готов к выдаче'))
        previous = None if self.columns['baggageevent']['previous_state'][0] else 'зарегистрирован'
        for number, (event, moment, new) in enumerate(steps, 1):
            if moment > now:
                break
            self.add('baggageevent', baggage_id=bid, 
                     event_type=self.value('baggageevent', 'event_type', event), event_time=moment,
                     previous_state=previous, new_state=self.value('baggageevent', 'new_state', new))
            previous = new
        self.rows['baggage'][-1]['status'] = previous


def insert_data(conn, schema, data):
    for table in TABLES:
        rows = data.rows[table]
        if not rows:
            continue
        target = table
        frame = pd.DataFrame(rows).astype(object)
        frame = frame.where(pd.notna(frame), None)
        cols = list(frame.columns)
        casts = []
        for col in cols:
            _, ns, typ, element = data.columns[table][col]
            cast = sql.SQL('%s::{}[]').format(sql.Identifier(ns, element)) if element else sql.Placeholder()
            casts.append(cast)
        query = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
            sql.Identifier(schema, target), sql.SQL(', ').join(map(sql.Identifier, cols)),
            sql.SQL(', ').join(casts))
        with conn.cursor() as cur:
            cur.executemany(query, list(frame.itertuples(index=False, name=None)))
        if 'id' in cols:
            sequence = conn.execute('SELECT pg_get_serial_sequence(%s, %s)',
                                    (sql.Identifier(schema, target).as_string(conn), 'id')).fetchone()[0]
            if sequence:
                conn.execute('SELECT setval(%s::regclass, %s, true)', (sequence, max(row['id'] for row in rows)))
        print(f'{target}: {len(rows)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', default='.env', help='путь к .env Docker Compose')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=5432, help='порт на компьютере, не контейнера')
    parser.add_argument('--country', default='RU', help='ISO-код страны для справочников')
    parser.add_argument('--cache', default='.aviation_cache', help='кэш открытых данных OpenFlights')
    parser.add_argument('--schema', default='goida-airlines')
    parser.add_argument('--days', type=int, default=21)
    parser.add_argument('--planes', type=int, default=6)
    parser.add_argument('--seed', type=int, default=69)
    parser.add_argument('--start-date', type=date.fromisoformat, help='YYYY-MM-DD; по умолчанию 14 дней назад')
    args = parser.parse_args()
    load_dotenv(args.env)
    missing = [key for key in ('POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD') if not os.getenv(key)]
    if missing:
        parser.error('Заполни .env: ' + ', '.join(missing))
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    start = args.start_date or now.date() - timedelta(days=14)
    try:
        with psycopg.connect(host=args.host, port=args.port, dbname=os.environ['POSTGRES_DB'],
                             user=os.environ['POSTGRES_USER'], password=os.environ['POSTGRES_PASSWORD'],
                             connect_timeout=10) as conn:
            columns, enums = read_schema(conn, args.schema)
            absent = [t for t in TABLES if t not in columns]
            if absent:
                raise ValueError('Не найдены таблицы: ' + ', '.join(absent))
            for table in TABLES:
                target = table
                if conn.execute(sql.SQL('SELECT EXISTS (SELECT 1 FROM {})').format(
                        sql.Identifier(args.schema, target))).fetchone()[0]:
                    raise ValueError('Генератор рассчитан на пустую БД. В таблице ' + target + ' уже есть данные.')
            if 'bpl_id' in columns['passenger'] or 'booking_id' in columns['passenger']:
                raise ValueError('Убери bpl_id/booking_id из Passenger: связь N:N хранится в BookingPassengerList.')
            data = Data(columns, enums, args.seed)
            data.build(start, args.days, args.planes, now, args.country, args.cache)
            insert_data(conn, args.schema, data)
        print('Готово. Данные сохранены одной транзакцией.')
    except (psycopg.Error, ValueError, OSError) as exc:
        parser.exit(1, f'Ошибка: {exc}\nИзменения транзакции не сохранены.\n')


if __name__ == '__main__':
    main()
