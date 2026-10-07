"""Estimate vehicle parking from adjacent rides without exposing ride timestamps."""
from datetime import datetime
from math import cos, hypot, pi


def stop_durations(dataset):
    result = {ride['id']: None for ride in dataset['rides']}
    uncertain_months = {ride['source_month'] for ride in dataset['rides'] if ride['started_at'] is None}
    uncertain_months.update(month['month'] for month in dataset['months'] if month['list_complete'] is not True)
    tracks = {track['ride_id']: track['points'] for track in dataset['tracks']}
    clock = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))
    rides = sorted((ride for ride in dataset['rides'] if ride['started_at'] is not None),
                   key=lambda ride: (clock(ride['started_at']), ride['id']))
    previous_end = None
    for index, (arrival, departure) in enumerate(zip(rides, rides[1:])):
        if index > 0 and rides[index - 1]['ended_at']:
            ended = clock(rides[index - 1]['ended_at'])
            previous_end = max(previous_end, ended) if previous_end else ended
        arriving_points, leaving_points = tracks.get(arrival['id']), tracks.get(departure['id'])
        if not arrival['ended_at'] or not arriving_points or not leaving_points:
            continue
        if (previous_end and clock(arrival['started_at']) < previous_end) or clock(arrival['started_at']) == clock(departure['started_at']):
            continue
        if arrival['source_month'] in uncertain_months or departure['source_month'] in uncertain_months:
            continue
        seconds = (clock(departure['started_at']) - clock(arrival['ended_at'])).total_seconds()
        if not 0 <= seconds <= 86400:
            continue
        a, b = arriving_points[-1], leaving_points[0]
        latitude = (a['latitude'] + b['latitude']) * pi / 360
        distance = hypot((a['longitude'] - b['longitude']) * cos(latitude), a['latitude'] - b['latitude']) * 6371008.8 * pi / 180
        if distance <= 100:
            result[arrival['id']] = seconds
    return result
