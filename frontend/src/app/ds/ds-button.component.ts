import { Component, input, output } from '@angular/core';

export type DsButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type DsButtonSize = 'md' | 'sm';

@Component({
  selector: 'ds-button',
  standalone: true,
  host: {
    '[class.ds-btn-full]': 'fullWidth()',
    '[style.pointer-events]': '(disabled() || loading()) ? "none" : null',
  },
  template: `
    <button
      [type]="type()"
      [class]="'ds-btn ds-btn-' + variant() + ' ds-btn-' + size()"
      [disabled]="disabled() || loading()"
      [attr.aria-busy]="loading() ? 'true' : null"
      [attr.aria-label]="ariaLabel() || null"
      (click)="handleClick($event)"
    >
      @if (loading()) {
        <span class="ds-btn-spinner" aria-hidden="true"></span>
      }
      <ng-content />
    </button>
  `,
  styles: `
    :host {
      display: inline-block;
    }

    :host(.ds-btn-full) {
      display: block;
      width: 100%;
    }

    .ds-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: var(--space-2);
      width: 100%;
      min-height: var(--control-height);
      padding: var(--space-2) var(--space-4);
      border: 1px solid transparent;
      border-radius: var(--radius-md);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      line-height: var(--leading-sm);
      font-weight: var(--weight-medium);
      text-decoration: none;
      cursor: pointer;
      transition:
        background-color var(--motion-fast) var(--ease-standard),
        border-color var(--motion-fast) var(--ease-standard),
        color var(--motion-fast) var(--ease-standard);
    }

    .ds-btn-sm {
      min-height: var(--control-height-sm);
      padding: var(--space-1) var(--space-3);
    }

    .ds-btn-primary {
      background: var(--color-primary);
      color: var(--color-text-inverse);
    }

    .ds-btn-primary:hover:not(:disabled) {
      background: var(--color-primary-hover);
    }

    .ds-btn-primary:active:not(:disabled) {
      background: var(--color-primary-active);
    }

    .ds-btn-secondary {
      background: var(--color-surface);
      color: var(--color-text);
      border-color: var(--color-border-strong);
    }

    .ds-btn-secondary:hover:not(:disabled) {
      background: var(--color-surface-muted);
    }

    .ds-btn-ghost {
      background: transparent;
      color: var(--color-primary);
    }

    .ds-btn-ghost:hover:not(:disabled) {
      background: var(--color-surface-muted);
      color: var(--color-primary-hover);
    }

    .ds-btn-danger {
      background: var(--color-danger);
      color: var(--color-text-inverse);
    }

    .ds-btn-danger:hover:not(:disabled) {
      background: var(--color-danger-hover);
    }

    .ds-btn:disabled {
      background: var(--color-surface-muted);
      color: var(--color-text-disabled);
      border-color: var(--color-border);
      cursor: not-allowed;
    }

    .ds-btn-spinner {
      width: 0.875rem;
      height: 0.875rem;
      border: 2px solid currentColor;
      border-right-color: transparent;
      border-radius: var(--radius-pill);
      animation: ds-spin 700ms linear infinite;
    }

    @keyframes ds-spin {
      to {
        transform: rotate(360deg);
      }
    }
  `,
})
export class DsButtonComponent {
  readonly variant = input<DsButtonVariant>('primary');
  readonly size = input<DsButtonSize>('md');
  readonly type = input<'button' | 'submit' | 'reset'>('button');
  readonly disabled = input(false);
  readonly loading = input(false);
  readonly fullWidth = input(false);
  readonly ariaLabel = input<string | undefined>(undefined);
  readonly pressed = output<MouseEvent>();

  handleClick(event: MouseEvent): void {
    if (this.disabled() || this.loading()) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    this.pressed.emit(event);
  }
}
