import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { DsAlertBannerComponent } from './ds-alert-banner.component';

@Component({
  standalone: true,
  imports: [DsAlertBannerComponent],
  template: `
    <ds-alert-banner
      [tone]="tone()"
      title="Aviso"
      message="Ocurrió un problema"
      actionLabel="Reintentar"
      [dismissible]="true"
      (action)="onAction()"
      (dismissed)="onDismiss()"
    />
  `,
})
class TestAlertHostComponent {
  readonly tone = signal<'info' | 'success' | 'warning' | 'danger'>('danger');
  onAction = vi.fn();
  onDismiss = vi.fn();
}

describe('DsAlertBannerComponent', () => {
  it('usa role="alert" para danger/warning y role="status" para info/success', () => {
    const fixture = TestBed.configureTestingModule({ imports: [TestAlertHostComponent] }).createComponent(
      TestAlertHostComponent,
    );
    fixture.detectChanges();

    const alertEl = fixture.nativeElement.querySelector('.ds-alert') as HTMLElement;
    expect(alertEl.getAttribute('role')).toBe('alert');

    fixture.componentInstance.tone.set('success');
    fixture.detectChanges();
    expect(alertEl.getAttribute('role')).toBe('status');

    const buttons = fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>;
    buttons[0].click();
    buttons[1].click();
    expect(fixture.componentInstance.onAction).toHaveBeenCalledTimes(1);
    expect(fixture.componentInstance.onDismiss).toHaveBeenCalledTimes(1);
  });
});
