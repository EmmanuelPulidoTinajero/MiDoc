import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { DsSkeletonComponent } from './ds-skeleton.component';

@Component({
  standalone: true,
  imports: [DsSkeletonComponent],
  template: `<ds-skeleton variant="row" [count]="4" label="Cargando citas" />`,
})
class TestSkeletonHostComponent {}

describe('DsSkeletonComponent', () => {
  it('renderiza la cantidad de bloques solicitada con role="status"', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestSkeletonHostComponent] }).createComponent(
      TestSkeletonHostComponent,
    );
    fixture.detectChanges();

    const group = fixture.nativeElement.querySelector('[role="status"]') as HTMLElement;
    const items = fixture.nativeElement.querySelectorAll('.ds-skeleton-item');
    expect(group).toBeTruthy();
    expect(group.textContent).toContain('Cargando citas');
    expect(items.length).toBe(4);
  });
});
