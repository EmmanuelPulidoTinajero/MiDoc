import { Component, input, output } from '@angular/core';
import { DsButtonComponent } from './ds-button.component';

export type DsEmptyStateIcon = 'calendar' | 'search' | 'file' | 'message' | 'inbox';

@Component({
  selector: 'ds-empty-state',
  standalone: true,
  imports: [DsButtonComponent],
  template: `
    <div class="ds-empty">
      <div class="ds-empty-icon" aria-hidden="true">
        @switch (icon()) {
          @case ('calendar') {
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="3" y="5" width="18" height="16" rx="2" />
              <path d="M16 3v4M8 3v4M3 10h18" />
            </svg>
          }
          @case ('search') {
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
          }
          @case ('file') {
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
              <path d="M14 3v5h5M9 13h6M9 17h4" />
            </svg>
          }
          @case ('message') {
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H8l-4 4V6a1 1 0 0 1 1-1Z" />
            </svg>
          }
          @default {
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M4 13h4l2 3h4l2-3h4" />
              <path d="M5 6h14l2 7v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5z" />
            </svg>
          }
        }
      </div>
      <h3 class="ds-empty-title">{{ title() }}</h3>
      <p class="ds-empty-desc">{{ description() }}</p>
      @if (actionLabel()) {
        <ds-button variant="primary" (pressed)="action.emit()">{{ actionLabel() }}</ds-button>
      }
    </div>
  `,
  styles: `
    .ds-empty {
      display: grid;
      justify-items: center;
      text-align: center;
      gap: var(--space-3);
      padding: var(--space-8) var(--space-4);
      border: 1px dashed var(--color-border-strong);
      border-radius: var(--radius-lg);
      background: var(--color-surface);
    }

    .ds-empty-icon {
      display: grid;
      place-items: center;
      width: 3rem;
      height: 3rem;
      border-radius: var(--radius-pill);
      background: var(--color-surface-muted);
      color: var(--color-primary);
    }

    .ds-empty-title {
      margin: 0;
      font-size: var(--text-lg);
      line-height: var(--leading-lg);
    }

    .ds-empty-desc {
      margin: 0;
      color: var(--color-text-soft);
      max-width: 44ch;
    }
  `,
})
export class DsEmptyStateComponent {
  readonly title = input.required<string>();
  readonly description = input.required<string>();
  readonly actionLabel = input('');
  readonly icon = input<DsEmptyStateIcon>('inbox');
  readonly action = output<void>();
}
