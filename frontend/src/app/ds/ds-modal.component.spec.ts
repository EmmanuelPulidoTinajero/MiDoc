import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { DsModalComponent } from './ds-modal.component';

@Component({
  standalone: true,
  imports: [DsModalComponent],
  template: `
    <button type="button" id="trigger">Abrir</button>
    <ds-modal [open]="open()" title="Confirmar acción" tone="danger" (closed)="onClosed()" (confirmed)="onConfirmed()">
      <p>¿Deseas continuar?</p>
    </ds-modal>
  `,
})
class TestModalHostComponent {
  readonly open = signal(false);
  onClosed = vi.fn();
  onConfirmed = vi.fn();
}

describe('DsModalComponent', () => {
  it('abre y cierra mediante dialog nativo, maneja Esc y restaura el foco al cerrar', async () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestModalHostComponent] }).createComponent(
      TestModalHostComponent,
    );
    fixture.detectChanges();

    const trigger = fixture.nativeElement.querySelector('#trigger') as HTMLButtonElement;
    const dialog = fixture.nativeElement.querySelector('dialog') as HTMLDialogElement;
    const showModalSpy = vi.fn(() => dialog.setAttribute('open', ''));
    const closeSpy = vi.fn(() => dialog.removeAttribute('open'));
    dialog.showModal = showModalSpy;
    dialog.close = closeSpy;

    document.body.appendChild(fixture.nativeElement);
    trigger.focus();

    fixture.componentInstance.open.set(true);
    fixture.detectChanges();
    await fixture.whenStable();

    expect(showModalSpy).toHaveBeenCalledTimes(1);
    expect(dialog.getAttribute('aria-labelledby')).toBeTruthy();

    dialog.dispatchEvent(new Event('cancel', { cancelable: true }));
    expect(fixture.componentInstance.onClosed).toHaveBeenCalledTimes(1);

    const focusSpy = vi.spyOn(trigger, 'focus');
    fixture.componentInstance.open.set(false);
    fixture.detectChanges();
    await fixture.whenStable();

    expect(closeSpy).toHaveBeenCalledTimes(1);
    expect(focusSpy).toHaveBeenCalledTimes(1);
    fixture.nativeElement.remove();
  });
});
