import { Component, computed, input, output } from '@angular/core';
import { DsButtonComponent } from './ds-button.component';

export type DsAlertTone = 'info' | 'success' | 'warning' | 'danger';

@Component({
  selector: 'ds-alert-banner',
  standalone: true,
  imports: [DsButtonComponent],
  template: `
    <div
      [class]="'ds-alert ds-alert-' + tone()"
      [attr.role]="ariaRole()"
      [attr.aria-live]="ariaLive()"
    >
      <div class="ds-alert-content">
        @if (title()) {
          <strong class="ds-alert-title">{{ title() }}</strong>
        }
        <p class="ds-alert-message">{{ message() }}</p>
      </div>
      @if (actionLabel() || dismissible()) {
        <div class="ds-alert-actions">
          @if (actionLabel()) {
            <ds-button variant="secondary" size="sm" (pressed)="action.emit()">
              {{ actionLabel() }}
            </ds-button>
          }
          @if (dismissible()) {
            <ds-button variant="ghost" size="sm" ariaLabel="Cerrar aviso" (pressed)="dismissed.emit()">
              Cerrar
            </ds-button>
          }
        </div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }

    .ds-alert {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-3);
      padding: var(--space-3) var(--space-4);
      border-radius: var(--radius-md);
      border: 1px solid var(--color-border);
      border-left-width: 4px;
    }

    .ds-alert-info {
      background: var(--color-info-soft);
      border-left-color: var(--color-info);
      color: var(--color-info);
    }

    .ds-alert-success {
      background: var(--color-success-soft);
      border-left-color: var(--color-success);
      color: var(--color-success);
    }

    .ds-alert-warning {
      background: var(--color-warning-soft);
      border-left-color: var(--color-warning);
      color: var(--color-warning);
    }

    .ds-alert-danger {
      background: var(--color-danger-soft);
      border-left-color: var(--color-danger);
      color: var(--color-danger);
    }

    .ds-alert-content {
      display: grid;
      gap: var(--space-1);
      min-width: 0;
    }

    .ds-alert-title {
      font-size: var(--text-sm);
      font-weight: var(--weight-semibold);
    }

    .ds-alert-message {
      margin: 0;
      font-size: var(--text-sm);
      line-height: var(--leading-sm);
      color: var(--color-text);
    }

    .ds-alert-actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
    }
  `,
})
export class DsAlertBannerComponent {
  readonly tone = input<DsAlertTone>('info');
  readonly title = input('');
  readonly message = input.required<string>();
  readonly actionLabel = input('');
  readonly dismissible = input(false);

  readonly action = output<void>();
  readonly dismissed = output<void>();

  readonly ariaRole = computed(() =>
    this.tone() === 'danger' || this.tone() === 'warning' ? 'alert' : 'status',
  );

  readonly ariaLive = computed(() =>
    this.ariaRole() === 'alert' ? 'assertive' : 'polite',
  );
}
