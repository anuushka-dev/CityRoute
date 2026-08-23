import { useEffect, useMemo } from 'react';
import {
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import type { Coordinate, DispatchMarker, MapLocation } from '../types/domain';
import { CITYROUTE_CENTER } from '../utils/validation';

const DEFAULT_ZOOM = 13;
const ROUTE_WEIGHT = 5;
const ROUTE_COMPARISON_WEIGHT = 4;
const ROUTE_OPACITY = 0.9;
const START_RADIUS = 7;
const STOP_RADIUS = 6;
const DRIVER_RADIUS = 7;
const ORDER_RADIUS = 5;
const MAP_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const MAP_ATTRIBUTION = '&copy; OpenStreetMap contributors';

export interface MapViewProps {
  routeGeometry: Coordinate[];
  comparisonGeometry?: Coordinate[];
  additionalSegments?: Coordinate[][];
  locations: MapLocation[];
  dispatchDrivers?: DispatchMarker[];
  dispatchOrders?: DispatchMarker[];
  dispatchLines?: Array<{ from: Coordinate; to: Coordinate; id: string }>;
  interactive?: boolean;
  onMapSelect?: (coordinate: Coordinate) => void;
}

function MapClickHandler({ onMapSelect }: { onMapSelect?: (coordinate: Coordinate) => void }) {
  useMapEvents({ click: (event) => onMapSelect?.({ lat: event.latlng.lat, lon: event.latlng.lng }) });
  return null;
}

function ViewportController({ locations, extraPoints }: { locations: MapLocation[]; extraPoints: Coordinate[] }) {
  const map = useMap();
  const points = useMemo(() => [
    ...locations.map((location) => [location.coordinate.lat, location.coordinate.lon] as [number, number]),
    ...extraPoints.map((point) => [point.lat, point.lon] as [number, number]),
  ], [locations, extraPoints]);

  useEffect(() => {
    if (points.length >= 2) map.fitBounds(points, { padding: [40, 40], maxZoom: 14 });
  }, [map, points]);

  return null;
}

export function MapView({
  routeGeometry,
  comparisonGeometry = [],
  additionalSegments = [],
  locations,
  dispatchDrivers = [],
  dispatchOrders = [],
  dispatchLines = [],
  interactive = false,
  onMapSelect,
}: MapViewProps) {
  const extraPoints = useMemo(() => [...routeGeometry.slice(0, 1), ...routeGeometry.slice(-1), ...comparisonGeometry.slice(0, 1), ...comparisonGeometry.slice(-1)], [routeGeometry, comparisonGeometry]);

  return (
    <MapContainer center={[CITYROUTE_CENTER.lat, CITYROUTE_CENTER.lon]} zoom={DEFAULT_ZOOM} className="map-container" zoomControl={false} scrollWheelZoom>
      <TileLayer attribution={MAP_ATTRIBUTION} url={MAP_TILE_URL} maxZoom={19} />
      {interactive && <MapClickHandler onMapSelect={onMapSelect} />}
      <ViewportController locations={locations} extraPoints={extraPoints} />

      {routeGeometry.length >= 2 && <Polyline positions={routeGeometry.map((point) => [point.lat, point.lon])} pathOptions={{ className: 'route-primary-line', weight: ROUTE_WEIGHT, opacity: ROUTE_OPACITY }} />}
      {comparisonGeometry.length >= 2 && <Polyline positions={comparisonGeometry.map((point) => [point.lat, point.lon])} pathOptions={{ className: 'route-comparison-line', weight: ROUTE_COMPARISON_WEIGHT, opacity: 0.7, dashArray: '10 8' }} />}
      {additionalSegments.map((segment, index) => segment.length >= 2 && <Polyline key={`segment-${index}`} positions={segment.map((point) => [point.lat, point.lon])} pathOptions={{ className: 'route-primary-line', weight: ROUTE_WEIGHT, opacity: ROUTE_OPACITY }} />)}

      {locations.map((location, index) => (
        <CircleMarker
          key={location.id}
          center={[location.coordinate.lat, location.coordinate.lon]}
          radius={index === 0 ? START_RADIUS : STOP_RADIUS}
          pathOptions={{ className: index === 0 ? 'cityroute-marker-start' : 'cityroute-marker-stop' }}
        >
          <Popup><strong>{location.label}</strong><br />{location.coordinate.lat.toFixed(5)}, {location.coordinate.lon.toFixed(5)}</Popup>
        </CircleMarker>
      ))}

      {dispatchDrivers.map((driver) => (
        <CircleMarker key={`driver-${driver.id}`} center={[driver.coordinate.lat, driver.coordinate.lon]} radius={DRIVER_RADIUS} pathOptions={{ className: 'cityroute-marker-driver' }}>
          <Popup><strong>{driver.label}</strong></Popup>
        </CircleMarker>
      ))}

      {dispatchOrders.map((order) => (
        <CircleMarker key={`order-${order.id}`} center={[order.coordinate.lat, order.coordinate.lon]} radius={ORDER_RADIUS} pathOptions={{ className: 'cityroute-marker-order' }}>
          <Popup><strong>{order.label}</strong></Popup>
        </CircleMarker>
      ))}

      {dispatchLines.map((line) => (
        <Polyline key={`dispatch-${line.id}`} positions={[[line.from.lat, line.from.lon], [line.to.lat, line.to.lon]]} pathOptions={{ className: 'dispatch-line', weight: 3, dashArray: '7 7', opacity: 0.8 }} />
      ))}
    </MapContainer>
  );
}
