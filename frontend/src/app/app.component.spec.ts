import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppComponent } from './app.component';
import { setApiConfigForTest } from './api.service';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('AppComponent', () => {
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

  it('no contiene texto de demostración ni placeholder de correo y el skip-link enfoca #main-content sin mutar el hash', () => {
    TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent as string;
    expect(text).not.toContain('Datos de demostración');
    expect(text).not.toContain('El envío por correo todavía no está disponible');

    const mainEl = fixture.nativeElement.querySelector('#main-content') as HTMLElement;
    const focusSpy = vi.spyOn(mainEl, 'focus');
    const skipLink = fixture.nativeElement.querySelector('.skip-link') as HTMLAnchorElement;
    const clickEvent = new MouseEvent('click', { cancelable: true });
    skipLink.dispatchEvent(clickEvent);

    expect(clickEvent.defaultPrevented).toBe(true);
    expect(focusSpy).toHaveBeenCalledTimes(1);
    fixture.destroy();
  });

  it('muestra enlaces de navegación por rol y gestiona el panel de avisos y marcado como leído', async () => {
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-1',
        user: { id: 'p1', email: 'ana@midoc.mx', role: 'PACIENTE', name: 'Ana' },
      }),
    );

    TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await tick();

    httpMock.expectOne('http://localhost:3000/api/me').flush({
      data: { id: 'p1', email: 'ana@midoc.mx', role: 'PACIENTE', name: 'Ana' },
    });
    httpMock.expectOne('http://localhost:3000/api/notifications').flush({
      data: [
        {
          id: 'n1',
          type: 'RECORDATORIO_CITA',
          title: 'Cita mañana',
          message: 'Tienes consulta a las 10:00',
          createdAt: '2026-11-18T12:00:00Z',
          read: false,
        },
      ],
    });
    await tick();
    fixture.detectChanges();

    const navText = (fixture.nativeElement.querySelector('nav') as HTMLElement).textContent ?? '';
    expect(navText).toContain('Buscar profesionales');
    expect(navText).toContain('Mis citas');
    expect(navText).toContain('Mi expediente');
    expect(navText).toContain('Mensajes');
    expect(navText).not.toContain('Mi panel');

    fixture.componentInstance.toggleNotifications();
    await tick();
    httpMock.expectOne('http://localhost:3000/api/notifications').flush({
      data: [
        {
          id: 'n1',
          type: 'RECORDATORIO_CITA',
          title: 'Cita mañana',
          message: 'Tienes consulta a las 10:00',
          createdAt: '2026-11-18T12:00:00Z',
          read: false,
        },
      ],
    });
    await tick();
    fixture.detectChanges();

    const drawerText = fixture.nativeElement.querySelector('#notification-list')?.textContent ?? '';
    expect(drawerText).toContain('Cita mañana');
    expect(drawerText).not.toContain('El envío por correo');

    const itemBtn = fixture.nativeElement.querySelector('.notification-item') as HTMLButtonElement;
    itemBtn.click();
    await tick();
    httpMock.expectOne('http://localhost:3000/api/notifications/n1/read').flush({
      data: {
        id: 'n1',
        type: 'RECORDATORIO_CITA',
        title: 'Cita mañana',
        message: 'Tienes consulta a las 10:00',
        createdAt: '2026-11-18T12:00:00Z',
        read: true,
      },
    });
    await tick();
    fixture.detectChanges();
    expect(fixture.componentInstance.unreadCount()).toBe(0);
    fixture.destroy();
  });
});
