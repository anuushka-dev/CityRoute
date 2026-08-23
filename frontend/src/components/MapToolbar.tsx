interface MapToolbarProps {
  mode: 'route' | 'stops' | 'dispatch';
  onModeChange: (mode: 'route' | 'stops' | 'dispatch') => void;
}

const MODES: Array<{ id: 'route' | 'stops' | 'dispatch'; label: string }> = [
  { id: 'route', label: 'Route' },
  { id: 'stops', label: 'Stops' },
  { id: 'dispatch', label: 'Dispatch' },
];

export function MapToolbar({ mode, onModeChange }: MapToolbarProps) {
  return (
    <div className="map-toolbar" aria-label="CityRoute mode">
      {MODES.map((item) => (
        <button
          className={`map-mode-button ${mode === item.id ? 'map-mode-button-active' : ''}`}
          key={item.id}
          type="button"
          onClick={() => onModeChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
