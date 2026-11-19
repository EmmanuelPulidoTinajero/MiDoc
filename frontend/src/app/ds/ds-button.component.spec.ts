import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { DsButtonComponent } from './ds-button.component';

@Component({
  standalone: true,
  imports: [DsButtonComponent],
  template: `
    <ds-button
      [variant]="variant"
      [disabled]="disabled"
      [loading]="loading"
      (pressed)="onPressed()"
    >
      Guardar cambios
    </ds-button>
  `,
})
class TestHostComponent {
  variant: 'primary' | 'secondary' | 'ghost' | 'danger' = 'primary';
  disabled = false;
  loading = false;
  onPressed = vi.fn();
}

describe('DsButtonComponent', () => {
  it('renderiza la variante solicitada y emite pressed al hacer clic', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestHostComponent] }).createComponent(
      TestHostComponent,
    );
    fixture.componentInstance.variant = 'danger';
    fixture.detectChanges();

    const button = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    expect(button.className).toContain('ds-btn-danger');
    expect(button.textContent).toContain('Guardar cambios');

    button.click();
    expect(fixture.componentInstance.onPressed).toHaveBeenCalledTimes(1);
  });

  it('suprime el clic cuando está deshabilitado o cargando y expone aria-busy', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestHostComponent] }).createComponent(
      TestHostComponent,
    );
    fixture.componentInstance.loading = true;
    fixture.detectChanges();

    const button = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');

    button.click();
    expect(fixture.componentInstance.onPressed).not.toHaveBeenCalled();
  });
});
