import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { DsEmptyStateComponent } from './ds-empty-state.component';

@Component({
  standalone: true,
  imports: [DsEmptyStateComponent],
  template: `
    <ds-empty-state
      title="Sin citas programadas"
      description="Explora el directorio para agendar tu primera consulta."
      actionLabel="Buscar profesionales"
      icon="calendar"
      (action)="onAction()"
    />
  `,
})
class TestEmptyHostComponent {
  onAction = vi.fn();
}

describe('DsEmptyStateComponent', () => {
  it('muestra título, descripción, ícono decorativo y emite action al pulsar el botón', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestEmptyHostComponent] }).createComponent(
      TestEmptyHostComponent,
    );
    fixture.detectChanges();

    const svg = fixture.nativeElement.querySelector('.ds-empty-icon') as HTMLElement;
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    expect(fixture.nativeElement.textContent).toContain('Sin citas programadas');

    const btn = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    btn.click();
    expect(fixture.componentInstance.onAction).toHaveBeenCalledTimes(1);
  });
});
