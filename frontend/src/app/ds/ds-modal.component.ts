import { Component, ElementRef, effect, input, output, viewChild } from '@angular/core';
import { DsButtonComponent } from './ds-button.component';

let nextModalId = 0;

@Component({
  selector: 'ds-modal',
  standalone: true,
  imports: [DsButtonComponent],
  template: `
    <dialog
      #dialogEl
      class="ds-modal"
      [attr.aria-labelledby]="titleId"
      (cancel)="onCancel($event)"
      (click)="onBackdropClick($event)"
    >
      <div class="ds-modal-surface" (click)="$event.stopPropagation()">
        <header class="ds-modal-header">
          <h2 [id]="titleId" class="ds-modal-title">{{ title() }}</h2>
          <ds-button
            variant="ghost"
            size="sm"
            ariaLabel="Cerrar"
            [disabled]="busy()"
            (pressed)="requestClose()"
          >
            Cerrar
          </ds-button>
        </header>
        <div class="ds-modal-body">
          <ng-content />
        </div>
        <footer class="ds-modal-footer">
          @if (showDefaultActions()) {
            <ds-button
              variant="secondary"
              [disabled]="busy()"
              (pressed)="requestClose()"
            >
              {{ cancelLabel() }}
            </ds-button>
            <ds-button
              [variant]="tone() === 'danger' ? 'danger' : 'primary'"
              [loading]="busy()"
              (pressed)="confirmed.emit()"
            >
              {{ confirmLabel() }}
            </ds-button>
          } @else {
            <ng-content select="[dsModalActions]" />
          }
        </footer>
      </div>
    </dialog>
  `,
  styles: `
    .ds-modal {
      width: min(32rem, calc(100vw - var(--space-6)));
      max-width: 100%;
      padding: 0;
      border: 1px solid var(--color-border);
      border-radius: var(--radius-xl);
      background: var(--color-surface);
      color: var(--color-text);
      box-shadow: var(--shadow-3);
      z-index: var(--z-modal);
    }

    .ds-modal::backdrop {
      background: var(--color-backdrop);
    }

    .ds-modal-surface {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-4);
      padding: var(--space-6);
    }

    .ds-modal-surface > * {
      min-width: 0;
    }

    .ds-modal-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--space-3);
      border-bottom: 1px solid var(--color-border);
      padding-bottom: var(--space-3);
    }

    .ds-modal-title {
      margin: 0;
      font-size: var(--text-xl);
      line-height: var(--leading-xl);
    }

    .ds-modal-body {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-3);
      min-width: 0;
    }

    .ds-modal-body > * {
      min-width: 0;
    }

    .ds-modal-footer {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: var(--space-2);
      border-top: 1px solid var(--color-border);
      padding-top: var(--space-3);
    }

    .ds-modal-footer:empty {
      display: none;
    }
  `,
})
export class DsModalComponent {
  readonly open = input.required<boolean>();
  readonly title = input.required<string>();
  readonly tone = input<'default' | 'danger'>('default');
  readonly confirmLabel = input('Confirmar');
  readonly cancelLabel = input('Cancelar');
  readonly showDefaultActions = input(true);
  readonly busy = input(false);

  readonly closed = output<void>();
  readonly confirmed = output<void>();

  readonly titleId = `ds-modal-title-${++nextModalId}`;
  private readonly dialogRef = viewChild<ElementRef<HTMLDialogElement>>('dialogEl');
  private previousActiveElement: HTMLElement | null = null;
  private isShown = false;

  constructor() {
    effect(() => {
      const shouldOpen = this.open();
      const dialog = this.dialogRef()?.nativeElement;
      if (!dialog) return;

      if (shouldOpen && !this.isShown) {
        this.previousActiveElement =
          typeof document !== 'undefined' ? (document.activeElement as HTMLElement | null) : null;
        if (typeof dialog.showModal === 'function') {
          if (!dialog.open) dialog.showModal();
        } else {
          dialog.setAttribute('open', '');
        }
        this.isShown = true;
      } else if (!shouldOpen && this.isShown) {
        if (typeof dialog.close === 'function') {
          if (dialog.open) dialog.close();
        } else {
          dialog.removeAttribute('open');
        }
        this.isShown = false;
        const prev = this.previousActiveElement;
        this.previousActiveElement = null;
        if (prev && prev.isConnected && typeof prev.focus === 'function') {
          prev.focus();
        }
      }
    });
  }

  onCancel(event: Event): void {
    event.preventDefault();
    this.requestClose();
  }

  onBackdropClick(event: MouseEvent): void {
    const dialog = this.dialogRef()?.nativeElement;
    if (dialog && event.target === dialog) {
      this.requestClose();
    }
  }

  requestClose(): void {
    if (this.busy()) return;
    this.closed.emit();
  }
}
