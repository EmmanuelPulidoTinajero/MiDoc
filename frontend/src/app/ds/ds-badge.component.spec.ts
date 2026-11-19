import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { DsBadgeComponent } from './ds-badge.component';

@Component({
  standalone: true,
  imports: [DsBadgeComponent],
  template: `
    <ds-badge [status]="status()" />
    <ds-badge tone="info">Personalizado</ds-badge>
  `,
})
class TestBadgeHostComponent {
  readonly status = signal('CONFIRMADA');
}

describe('DsBadgeComponent', () => {
  it('traduce estados crudos de base de datos a etiquetas en español y tono semántico', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestBadgeHostComponent] }).createComponent(
      TestBadgeHostComponent,
    );
    fixture.detectChanges();

    const badges = fixture.nativeElement.querySelectorAll('.ds-badge') as NodeListOf<HTMLElement>;
    expect(badges[0].textContent?.trim()).toBe('Confirmada');
    expect(badges[0].getAttribute('data-tone')).toBe('success');
    expect(badges[1].textContent?.trim()).toBe('Personalizado');
    expect(badges[1].getAttribute('data-tone')).toBe('info');
  });

  it('traduce PENDIENTE, CANCELADA, COMPLETADA, ACTIVA e INACTIVA', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestBadgeHostComponent] }).createComponent(
      TestBadgeHostComponent,
    );

    const expected: Array<[string, string, string]> = [
      ['PENDIENTE', 'Pendiente', 'warning'],
      ['CANCELADA', 'Cancelada', 'danger'],
      ['COMPLETADA', 'Completada', 'info'],
      ['ACTIVA', 'Activa', 'success'],
      ['INACTIVA', 'Vencida', 'danger'],
    ];

    for (const [raw, label, tone] of expected) {
      fixture.componentInstance.status.set(raw);
      fixture.detectChanges();
      const badge = fixture.nativeElement.querySelector('.ds-badge') as HTMLElement;
      expect(badge.textContent?.trim()).toBe(label);
      expect(badge.getAttribute('data-tone')).toBe(tone);
    }
  });
});
