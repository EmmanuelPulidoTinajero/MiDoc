import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { DsPageHeaderComponent } from './ds-page-header.component';

@Component({
  standalone: true,
  imports: [DsPageHeaderComponent],
  template: `
    <ds-page-header eyebrow="Consultorio" title="Mi panel" subtitle="Administra tu suscripción y horario." [headingLevel]="2">
      <button dsPageActions type="button">Actualizar</button>
    </ds-page-header>
  `,
})
class TestPageHeaderHostComponent {}

describe('DsPageHeaderComponent', () => {
  it('renderiza eyebrow, título en el nivel indicado, subtítulo y acciones', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestPageHeaderHostComponent] }).createComponent(
      TestPageHeaderHostComponent,
    );
    fixture.detectChanges();

    const h2 = fixture.nativeElement.querySelector('h2') as HTMLElement;
    expect(h2.textContent?.trim()).toBe('Mi panel');
    expect(fixture.nativeElement.textContent).toContain('Consultorio');
    expect(fixture.nativeElement.textContent).toContain('Actualizar');
  });
});
