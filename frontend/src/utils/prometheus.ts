import type { MetricSample } from '../types/domain';

function parseLabels(raw: string | undefined): Record<string, string> {
  if (!raw) return {};
  const labels: Record<string, string> = {};
  for (const match of raw.matchAll(/([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"])*)"/g)) {
    labels[match[1]] = match[2].replace(/\\"/g, '"').replace(/\\\\/g, '\\');
  }
  return labels;
}

export function parsePrometheusText(text: string): MetricSample[] {
  const samples: MetricSample[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line || line.startsWith('#')) continue;
    const match = line.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)$/);
    if (!match) continue;
    const value = Number(match[3]);
    if (!Number.isFinite(value)) continue;
    samples.push({ name: match[1], labels: parseLabels(match[2]), value });
  }
  return samples;
}

export function metricValue(samples: MetricSample[], name: string, labels: Record<string, string> = {}): number | null {
  const sample = samples.find((candidate) => candidate.name === name && Object.entries(labels).every(([key, value]) => candidate.labels[key] === value));
  return sample?.value ?? null;
}

export function metricPrefix(samples: MetricSample[], prefix: string): MetricSample[] {
  return samples.filter((sample) => sample.name.startsWith(prefix));
}
