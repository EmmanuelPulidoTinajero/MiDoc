import { Component, input } from '@angular/core';

@Component({
  selector: 'ds-card',
  standalone: true,
  template: `
    <div
      [class]="'ds-card ds-card-' + tone() + ' ds-card-pad-' + padding()"
      [class.ds-card-selected]="selected()"
      [class.ds-card-interactive]="interactive()"
    >
      <div class="ds-card-header"><ng-content select="[dsCardHeader]" /></div>
      <div class="ds-card-body"><ng-content /></div>
      <div class="ds-card-footer"><ng-content select="[dsCardFooter]" /></div>
    </div>
  `,
  styles: `
    :host {
      display: block;
      min-width: 0;
    }

    .ds-card {
      min-width: 0;
      background: var(--color-surface);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-1);
      transition:
        border-color var(--motion-fast) var(--ease-standard),
        box-shadow var(--motion-fast) var(--ease-standard);
    }

    .ds-card-body {
      min-width: 0;
    }

    .ds-card-muted {
      background: var(--color-surface-muted);
    }

    .ds-card-pad-md {
      padding: var(--space-5);
    }

    .ds-card-pad-lg {
      padding: var(--space-6);
    }

    .ds-card-pad-none {
      padding: 0;
    }

    .ds-card-interactive:hover {
      border-color: var(--color-border-strong);
      box-shadow: var(--shadow-2);
    }

    .ds-card-selected {
      border-color: var(--color-primary);
      box-shadow: 0 0 0 2px var(--color-primary-soft);
    }

    .ds-card-header:empty,
    .ds-card-footer:empty {
      display: none;
    }

    .ds-card-header {
      padding-bottom: var(--space-3);
      margin-bottom: var(--space-3);
      border-bottom: 1px solid var(--color-border);
    }

    .ds-card-footer {
      padding-top: var(--space-3);
      margin-top: var(--space-3);
      border-top: 1px solid var(--color-border);
    }

    @media (max-width: 640px) {
      .ds-card-pad-md {
        padding: var(--space-4);
      }
      .ds-card-pad-lg {
        padding: var(--space-4);
      }
    }
  `,
})
export class DsCardComponent {
  readonly tone = input<'surface' | 'muted'>('surface');
  readonly selected = input(false);
  readonly interactive = input(false);
  readonly padding = input<'md' | 'lg' | 'none'>('md');
}
