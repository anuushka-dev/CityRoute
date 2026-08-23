import type { Coordinate } from '../types/domain';

export const CITYROUTE_BOUNDS = Object.freeze({
  south: 26.43,
  north: 26.50,
  west: 80.28,
  east: 80.38,
});

export const CITYROUTE_CENTER: Coordinate = Object.freeze({
  lat: 26.465,
  lon: 80.33,
});

export function isInsideCityRouteBounds(coordinate: Coordinate): boolean {
  return (
    coordinate.lat >= CITYROUTE_BOUNDS.south &&
    coordinate.lat <= CITYROUTE_BOUNDS.north &&
    coordinate.lon >= CITYROUTE_BOUNDS.west &&
    coordinate.lon <= CITYROUTE_BOUNDS.east
  );
}
