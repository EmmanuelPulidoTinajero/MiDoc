import { Component, input } from '@angular/core';

@Component({
  selector: 'ds-page-header',
  standalone: true,
  template: `
    <header class="ds-page-header">
      <div class="ds-page-header-copy">
        @if (eyebrow()) {
          <p class="eyebrow">{{ eyebrow() }}</p>
        }
        @if (headingLevel() === 2) {
          <h2 class="ds-page-title">{{ title() }}</h2>
        } @else {
          <h1 class="ds-page-title">{{ title() }}</h1>
        }
        @if (subtitle()) {
          <p class="ds-page-subtitle">{{ subtitle() }}</p>
        }
      </div>
      <div class="ds-page-actions">
        <ng-content select="[dsPageActions]" />
      </div>
    </header>
  `,
  styles: `
    :host {
      display: block;
      min-width: 0;
    }

    .ds-page-header {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-end;
      justify-content: space-between;
      gap: var(--space-4);
      padding-bottom: var(--space-4);
      margin-bottom: var(--space-5);
      border-bottom: 1px solid var(--color-border);
      min-width: 0;
    }

    .ds-page-header-copy {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-1);
      min-width: 0;
    }

    .ds-page-title {
      margin: 0;
      overflow-wrap: anywhere;
    }

    .ds-page-subtitle {
      margin: 0;
      color: var(--color-text-soft);
      max-width: var(--measure);
      overflow-wrap: anywhere;
    }

    .ds-page-actions:empty {
      display: none;
    }

    .ds-page-actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
    }
  `,
})
export class DsPageHeaderComponent {
  readonly eyebrow = input('');
  readonly title = input.required<string>();
  readonly subtitle = input('');
  readonly headingLevel = input<1 | 2>(1);
}
