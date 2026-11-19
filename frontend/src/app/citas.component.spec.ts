import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setApiConfigForTest } from './api.service';
import { CitasComponent } from './citas.component';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('CitasComponent', () => {
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
    setApiConfigForTest('http://localhost:3000', 'test', '');
  });

  afterEach(() => {
    httpMock?.verify();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('filtra por estado, traduce badges al español, mantiene Cerrar accesible con 0 slots y cancela vía DsModal', async () => {
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-p',
        user: { id: 'p1', email: 'ana@midoc.mx', role: 'PACIENTE', name: 'Ana' },
      }),
    );

    TestBed.configureTestingModule({
      imports: [CitasComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(CitasComponent);
    fixture.detectChanges();
    await tick();

    const futureIso = new Date(Date.now() + 86_400_000 * 3).toISOString();
    httpMock.expectOne('http://localhost:3000/api/appointments').flush({
      data: [
        {
          id: 'c1',
          patientId: 'p1',
          doctorId: 'd1',
          dateTime: futureIso,
          status: 'CONFIRMADA',
          doctorName: 'Dr. Sol',
          specialty: 'Medicina general',
        },
        {
          id: 'c2',
          patientId: 'p1',
          doctorId: 'd2',
          dateTime: '2026-01-01T10:00:00Z',
          status: 'COMPLETADA',
          doctorName: 'Dra. Luz',
          specialty: 'Pediatría',
        },
      ],
    });
    await tick();
    fixture.detectChanges();

    const badgeText = (fixture.nativeElement.querySelector('tbody .ds-badge') as HTMLElement).textContent?.trim();
    expect(badgeText).toBe('Confirmada');
    expect(fixture.nativeElement.textContent).not.toContain('CONFIRMADA');

    fixture.componentInstance.statusFilter.set('COMPLETADA');
    fixture.detectChanges();
    expect(fixture.componentInstance.filteredAppointments().length).toBe(1);
    fixture.componentInstance.statusFilter.set('TODAS');
    fixture.detectChanges();

    // Roving tabindex y navegación con ArrowLeft/ArrowRight en pestañas de estado
    const tabs = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]')) as HTMLButtonElement[];
    expect(tabs[0].getAttribute('tabindex')).toBe('0');
    expect(tabs[1].getAttribute('tabindex')).toBe('-1');
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    fixture.detectChanges();
    expect(fixture.componentInstance.statusFilter()).toBe('PENDIENTE');
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(tabs[1].getAttribute('tabindex')).toBe('0');
    expect(tabs[0].getAttribute('tabindex')).toBe('-1');
    tabs[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    fixture.detectChanges();
    expect(fixture.componentInstance.statusFilter()).toBe('TODAS');

    const reschedP = fixture.componentInstance.beginReschedule(fixture.componentInstance.appointments()[0]);
    await tick();
    httpMock
      .expectOne((req) => req.url === 'http://localhost:3000/api/doctors/d1/availability')
      .flush({ data: { slots: [] } });
    await reschedP;
    fixture.detectChanges();

    const dialogs = fixture.nativeElement.querySelectorAll('dialog') as NodeListOf<HTMLDialogElement>;
    const rescheduleDialog = dialogs[1];
    const closeBtns = Array.from(rescheduleDialog.querySelectorAll('button')).filter((b) =>
      b.textContent?.includes('Cerrar'),
    );
    expect(closeBtns.length).toBeGreaterThanOrEqual(1);
    closeBtns[closeBtns.length - 1].click();
    fixture.detectChanges();
    expect(fixture.componentInstance.rescheduling()).toBeNull();

    const confirmSpy = vi.spyOn(globalThis, 'confirm');
    fixture.componentInstance.requestCancel(fixture.componentInstance.appointments()[0]);
    fixture.detectChanges();
    expect(fixture.componentInstance.pendingCancel()?.id).toBe('c1');

    const cancelP = fixture.componentInstance.confirmCancel();
    await tick();
    httpMock.expectOne('http://localhost:3000/api/appointments/c1/status').flush({ data: { status: 'CANCELADA' } });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/appointments').flush({ data: [] });
    await cancelP;
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('muestra estado de consentimiento explícito en el formulario de consulta del doctor', async () => {
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-d',
        user: { id: 'u-d1', email: 'doc@midoc.mx', role: 'DOCTOR', name: 'Dr. Sol', doctorId: 'd1' },
      }),
    );

    TestBed.configureTestingModule({
      imports: [CitasComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(CitasComponent);
    fixture.detectChanges();
    await tick();

    const pastIso = new Date(Date.now() - 3_600_000).toISOString();
    httpMock.expectOne('http://localhost:3000/api/appointments').flush({
      data: [
        {
          id: 'c1',
          patientId: 'p-missing',
          doctorId: 'd1',
          dateTime: pastIso,
          status: 'CONFIRMADA',
          patientName: 'Carlos Pérez',
        },
      ],
    });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/doctor/patients').flush({ data: [] });
    await tick();
    fixture.detectChanges();

    const attendP = fixture.componentInstance.attend(fixture.componentInstance.appointments()[0]);
    fixture.componentInstance.diagnosis = 'Faringitis aguda';
    fixture.componentInstance.treatment = 'Reposo e hidratación';
    fixture.detectChanges();
    await tick();

    // Mientras patientConsentStatus === 'checking', el botón de envío permanece deshabilitado
    expect(fixture.componentInstance.patientConsentStatus()).toBe('checking');
    const submitBtnDuringCheck = fixture.nativeElement.querySelector('form button[type="submit"]') as HTMLButtonElement;
    expect(submitBtnDuringCheck.disabled).toBe(true);

    httpMock.expectOne('http://localhost:3000/api/doctor/patients').flush({ data: [] });
    await attendP;
    fixture.detectChanges();

    expect(fixture.componentInstance.patientConsentStatus()).toBe('missing');
    expect(fixture.nativeElement.textContent).toContain('Consentimiento pendiente');
    expect(submitBtnDuringCheck.disabled).toBe(true);

    const refreshP = fixture.componentInstance.refreshAuthorizedPatients();
    await tick();
    httpMock.expectOne('http://localhost:3000/api/doctor/patients').flush({
      data: [{ patientId: 'p-missing', name: 'Carlos Pérez', email: 'c@m.mx', accessSince: pastIso }],
    });
    await refreshP;
    fixture.detectChanges();

    expect(fixture.componentInstance.patientConsentStatus()).toBe('granted');
    expect(fixture.nativeElement.textContent).toContain('Consentimiento vigente');
    expect(submitBtnDuringCheck.disabled).toBe(false);
  });
});
