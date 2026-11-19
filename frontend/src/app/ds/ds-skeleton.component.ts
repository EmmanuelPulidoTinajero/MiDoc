import { Component, computed, input } from '@angular/core';

@Component({
  selector: 'ds-skeleton',
  standalone: true,
  template: `
    <div
      class="ds-skeleton-group"
      [class.ds-skeleton-cards]="variant() === 'card'"
      role="status"
      aria-live="polite"
    >
      <span class="sr-only">{{ label() }}</span>
      @for (item of items(); track item) {
        <div [class]="'ds-skeleton-item ds-skeleton-' + variant()" aria-hidden="true"></div>
      }
    </div>
  `,
  styles: `
    .ds-skeleton-group {
      display: grid;
      gap: var(--space-3);
    }

    .ds-skeleton-cards {
      grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
    }

    .ds-skeleton-item {
      background: var(--color-surface-muted);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md);
      animation: ds-skeleton-pulse 1.4s ease-in-out infinite;
    }

    .ds-skeleton-card {
      height: 10rem;
      border-radius: var(--radius-lg);
    }

    .ds-skeleton-row {
      height: 3rem;
    }

    .ds-skeleton-text {
      height: 1rem;
    }

    @keyframes ds-skeleton-pulse {
      0%,
      100% {
        background-color: var(--color-surface-muted);
      }
      50% {
        background-color: var(--color-border);
      }
    }
  `,
})
export class DsSkeletonComponent {
  readonly variant = input<'card' | 'row' | 'text'>('card');
  readonly count = input(3);
  readonly label = input('Cargando…');
  readonly items = computed(() => Array.from({ length: Math.max(1, this.count()) }, (_, index) => index));
}
