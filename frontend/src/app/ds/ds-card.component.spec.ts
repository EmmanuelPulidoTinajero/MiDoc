import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { DsCardComponent } from './ds-card.component';

@Component({
  standalone: true,
  imports: [DsCardComponent],
  template: `
    <ds-card [selected]="selected" [interactive]="interactive" tone="muted">
      <span dsCardHeader>Encabezado</span>
      <p>Cuerpo de tarjeta</p>
      <span dsCardFooter>Pie</span>
    </ds-card>
  `,
})
class TestCardHostComponent {
  selected = true;
  interactive = true;
}

describe('DsCardComponent', () => {
  it('proyecta encabezado, cuerpo, pie y aplica clases selected/interactive/muted', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestCardHostComponent] }).createComponent(
      TestCardHostComponent,
    );
    fixture.detectChanges();

    const card = fixture.nativeElement.querySelector('.ds-card') as HTMLElement;
    expect(card.className).toContain('ds-card-muted');
    expect(card.className).toContain('ds-card-selected');
    expect(card.className).toContain('ds-card-interactive');
    expect(card.textContent).toContain('Encabezado');
    expect(card.textContent).toContain('Cuerpo de tarjeta');
    expect(card.textContent).toContain('Pie');
  });
});
