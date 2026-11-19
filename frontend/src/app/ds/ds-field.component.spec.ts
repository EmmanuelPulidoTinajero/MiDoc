import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { DsControlDirective, DsFieldComponent } from './ds-field.component';

@Component({
  standalone: true,
  imports: [DsFieldComponent, DsControlDirective],
  template: `
    <ds-field label="Correo electrónico" hint="Usa tu correo registrado" [error]="error()" [required]="true" fieldId="correo-test">
      <input dsControl type="email" />
    </ds-field>
  `,
})
class TestFieldHostComponent {
  readonly error = signal('');
}

describe('DsFieldComponent y DsControlDirective', () => {
  it('enlaza label[for], id, aria-describedby y role="alert" cuando hay error', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestFieldHostComponent] }).createComponent(
      TestFieldHostComponent,
    );
    fixture.detectChanges();

    const label = fixture.nativeElement.querySelector('label') as HTMLLabelElement;
    const input = fixture.nativeElement.querySelector('input') as HTMLInputElement;

    expect(label.getAttribute('for')).toBe('correo-test');
    expect(input.id).toBe('correo-test');
    expect(input.getAttribute('aria-describedby')).toBe('correo-test-hint');
    expect(input.getAttribute('aria-invalid')).toBeNull();

    fixture.componentInstance.error.set('Ingresa un correo válido.');
    fixture.detectChanges();

    const alert = fixture.nativeElement.querySelector('[role="alert"]') as HTMLElement;
    expect(alert.textContent?.trim()).toBe('Ingresa un correo válido.');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(input.getAttribute('aria-describedby')).toBe('correo-test-hint correo-test-error');
  });
});
