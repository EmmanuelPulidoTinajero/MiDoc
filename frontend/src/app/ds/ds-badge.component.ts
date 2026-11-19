import { Component, computed, input } from '@angular/core';

export type DsBadgeTone = 'neutral' | 'success' | 'warning' | 'info' | 'danger';

const STATUS_MAP: Record<string, { label: string; tone: DsBadgeTone }> = {
  CONFIRMADA: { label: 'Confirmada', tone: 'success' },
  PENDIENTE: { label: 'Pendiente', tone: 'warning' },
  COMPLETADA: { label: 'Completada', tone: 'info' },
  CANCELADA: { label: 'Cancelada', tone: 'danger' },
  ACTIVA: { label: 'Activa', tone: 'success' },
  INACTIVA: { label: 'Vencida', tone: 'danger' },
  SIN_SUSCRIPCION: { label: 'Sin suscripción', tone: 'warning' },
  OTORGADO: { label: 'Otorgado', tone: 'success' },
  REVOCADO: { label: 'Revocado', tone: 'danger' },
  TEST: { label: 'Modo prueba', tone: 'warning' },
  LIVE: { label: 'Producción', tone: 'info' },
};

@Component({
  selector: 'ds-badge',
  standalone: true,
  template: `
    <span class="ds-badge" [attr.data-tone]="resolvedTone()">
      <span class="ds-badge-dot" aria-hidden="true"></span>
      @if (resolvedLabel()) {
        {{ resolvedLabel() }}
      }
      <ng-content />
    </span>
  `,
  styles: `
    :host {
      display: inline-block;
    }

    .ds-badge {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1);
      padding: 0.15rem var(--space-2);
      border-radius: var(--radius-pill);
      font-size: var(--text-xs);
      line-height: var(--leading-xs);
      font-weight: var(--weight-semibold);
      white-space: nowrap;
      background: var(--color-surface-muted);
      color: var(--color-text);
    }

    .ds-badge-dot {
      width: 0.4rem;
      height: 0.4rem;
      border-radius: var(--radius-pill);
      background: currentColor;
      flex-shrink: 0;
    }

    .ds-badge[data-tone='success'] {
      background: var(--color-success-soft);
      color: var(--color-success);
    }

    .ds-badge[data-tone='warning'] {
      background: var(--color-warning-soft);
      color: var(--color-warning);
    }

    .ds-badge[data-tone='info'] {
      background: var(--color-info-soft);
      color: var(--color-info);
    }

    .ds-badge[data-tone='danger'] {
      background: var(--color-danger-soft);
      color: var(--color-danger);
    }
  `,
})
export class DsBadgeComponent {
  readonly tone = input<DsBadgeTone | undefined>(undefined);
  readonly status = input<string | undefined>(undefined);

  private readonly mapped = computed(() => {
    const raw = this.status()?.trim().toUpperCase();
    return raw ? STATUS_MAP[raw] : undefined;
  });

  readonly resolvedTone = computed<DsBadgeTone>(() => this.tone() ?? this.mapped()?.tone ?? 'neutral');
  readonly resolvedLabel = computed<string>(() => this.mapped()?.label ?? '');
}
