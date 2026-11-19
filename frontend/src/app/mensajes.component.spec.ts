import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { setApiConfigForTest } from './api.service';
import { MensajesComponent } from './mensajes.component';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('MensajesComponent', () => {
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
    setApiConfigForTest('http://localhost:3000', 'test', '');
  });

  afterEach(() => {
    httpMock?.verify();
    localStorage.clear();
  });

  it('usa barra lateral sin <select> y resuelve doctores sólo por ID sin llamar a GET /api/doctors completo', async () => {
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-p',
        user: { id: 'p1', email: 'ana@midoc.mx', role: 'PACIENTE', name: 'Ana' },
      }),
    );

    TestBed.configureTestingModule({
      imports: [MensajesComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(MensajesComponent);
    fixture.detectChanges();
    await tick();

    httpMock.expectOne('http://localhost:3000/api/messages').flush({ data: [] });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/consents').flush({
      data: [{ doctorId: 'd1', doctorName: 'Dr. Sol', specialty: 'General', granted: true, updatedAt: '' }],
    });
    httpMock.expectOne('http://localhost:3000/api/appointments').flush({ data: [] });
    await tick();
    httpMock.expectNone('http://localhost:3000/api/doctors');
    httpMock.expectOne('http://localhost:3000/api/doctors/d1').flush({
      data: { id: 'd1', userId: 'u-d1', name: 'Dr. Sol', specialty: 'General', location: 'CDMX', price: 500 },
    });
    await tick();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('select')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Dr. Sol');

    const contactBtn = fixture.nativeElement.querySelector('.chat-contact-btn') as HTMLButtonElement;
    contactBtn.click();
    await tick();
    httpMock.expectOne('http://localhost:3000/api/messages/u-d1').flush({ data: [] });
    await tick();
    fixture.detectChanges();

    fixture.componentInstance.content = 'Hola doctor';
    const sendP = fixture.componentInstance.send();
    await tick();
    httpMock.expectOne('http://localhost:3000/api/messages').flush({
      data: { id: 'm1', senderId: 'p1', recipientId: 'u-d1', content: 'Hola doctor', createdAt: '2026-11-18T12:00:00Z', read: false },
    });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/messages/u-d1').flush({
      data: [{ id: 'm1', senderId: 'p1', recipientId: 'u-d1', content: 'Hola doctor', createdAt: '2026-11-18T12:00:00Z', read: false }],
    });
    await sendP;
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Hola doctor');
  });

  it('maneja limpiamente el error 402 cuando un doctor sin suscripción abre Mensajes', async () => {
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-d',
        user: { id: 'u-d1', email: 'doc@midoc.mx', role: 'DOCTOR', name: 'Dr. Sol', doctorId: 'd1' },
      }),
    );

    TestBed.configureTestingModule({
      imports: [MensajesComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(MensajesComponent);
    fixture.detectChanges();
    await tick();

    httpMock
      .expectOne('http://localhost:3000/api/messages')
      .flush({ error: 'Necesitas una suscripción activa' }, { status: 402, statusText: 'Payment Required' });
    await tick();
    fixture.detectChanges();

    expect(fixture.componentInstance.subscriptionRequired()).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('Activa tu suscripción para usar mensajes');
  });
});
