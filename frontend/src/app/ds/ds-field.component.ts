import { Component, Directive, computed, inject, input } from '@angular/core';

let nextFieldId = 0;

@Component({
  selector: 'ds-field',
  standalone: true,
  template: `
    <div class="ds-field" [class.ds-field-invalid]="!!error()">
      <label class="ds-field-label" [attr.for]="fieldId()">
        {{ label() }}
        @if (required()) {
          <span class="ds-field-required" aria-hidden="true">*</span>
        }
      </label>
      <ng-content />
      @if (hint()) {
        <span class="ds-field-hint" [id]="hintId()">{{ hint() }}</span>
      }
      @if (error()) {
        <span class="ds-field-error" [id]="errorId()" role="alert">{{ error() }}</span>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
      min-width: 0;
    }

    .ds-field {
      display: grid;
      gap: var(--space-1);
      min-width: 0;
    }

    .ds-field-label {
      display: block;
      font-size: var(--text-sm);
      line-height: var(--leading-sm);
      font-weight: var(--weight-medium);
      color: var(--color-text);
    }

    .ds-field-required {
      color: var(--color-danger);
      margin-left: 0.15rem;
    }

    .ds-field-hint {
      font-size: var(--text-xs);
      line-height: var(--leading-xs);
      color: var(--color-text-soft);
    }

    .ds-field-error {
      font-size: var(--text-xs);
      line-height: var(--leading-xs);
      color: var(--color-danger);
      font-weight: var(--weight-medium);
    }
  `,
})
export class DsFieldComponent {
  readonly label = input.required<string>();
  readonly hint = input('');
  readonly error = input('');
  readonly required = input(false);
  readonly fieldId = input(`ds-field-${++nextFieldId}`);

  readonly hintId = computed(() => `${this.fieldId()}-hint`);
  readonly errorId = computed(() => `${this.fieldId()}-error`);
  readonly describedBy = computed(() => {
    const ids: string[] = [];
    if (this.hint()) ids.push(this.hintId());
    if (this.error()) ids.push(this.errorId());
    return ids.join(' ') || null;
  });
}

@Directive({
  selector: 'input[dsControl], select[dsControl], textarea[dsControl]',
  standalone: true,
  host: {
    '[attr.id]': 'field ? field.fieldId() : null',
    '[attr.aria-invalid]': 'field?.error() ? "true" : null',
    '[attr.aria-describedby]': 'field?.describedBy() ?? null',
    '[attr.required]': 'field?.required() ? "" : null',
    class: 'ds-control',
    '[class.ds-control-error]': '!!field?.error()',
  },
})
export class DsControlDirective {
  readonly field = inject(DsFieldComponent, { optional: true });
}
