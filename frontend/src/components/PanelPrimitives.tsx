import type { ReactNode } from 'react';

export function PanelSection({ title, subtitle, action, children }: { title: string; subtitle?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel-section">
      <div className="section-heading">
        <div>
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function StatusDot({ state }: { state: 'ok' | 'warn' | 'bad' | 'neutral' }) {
  return <span className={`status-dot status-dot-${state}`} aria-hidden="true" />;
}

export function StatusPill({ label, state }: { label: string; state: 'ok' | 'warn' | 'bad' | 'neutral' }) {
  return <span className={`status-pill status-pill-${state}`}><StatusDot state={state} />{label}</span>;
}

export function CodeTag({ children }: { children: ReactNode }) {
  return <span className="code-tag">{children}</span>;
}
