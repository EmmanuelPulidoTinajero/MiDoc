import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { routes } from './app.routes';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { setApiConfigForTest } from './api.service';
import { BusquedaComponent } from './busqueda.component';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('BusquedaComponent', () => {
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
    setApiConfigForTest('http://localhost:3000', 'test', '');
    TestBed.configureTestingModule({
      imports: [BusquedaComponent],
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('carga el directorio al iniciar, calcula precios con promoción y envía parámetro sort', async () => {
    const fixture = TestBed.createComponent(BusquedaComponent);
    fixture.detectChanges();
    await tick();

    const initialReq = httpMock.expectOne('http://localhost:3000/api/doctors');
    initialReq.flush({
      data: [
        {
          id: 'doc-1',
          name: 'Dra. Elena Ruiz',
          specialty: 'Cardiología',
          location: 'CDMX',
          price: 1000,
          promotionSummary: {
            count: 1,
            maxDiscountPercent: 20,
            title: 'Chequeo preventivo',
            discountedPrice: 800,
          },
        },
      ],
    });
    await tick();
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Dra. Elena Ruiz');
    expect(text).toContain('$1000 MXN');
    expect(text).toContain('$800 MXN');
    expect(text).toContain('-20%');

    fixture.componentInstance.sort = 'PRICE_ASC';
    const searchPromise = fixture.componentInstance.search();
    await tick();
    const sortedReq = httpMock.expectOne('http://localhost:3000/api/doctors?sort=PRICE_ASC');
    sortedReq.flush({ data: [] });
    await searchPromise;
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Sin resultados para estos filtros');
  });

  it('seleccionar un horario en Paso 2 no reserva hasta confirmar en Paso 3', async () => {
    TestBed.resetTestingModule();
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-p',
        user: { id: 'p1', email: 'ana@midoc.mx', role: 'PACIENTE', name: 'Ana' },
      }),
    );
    TestBed.configureTestingModule({
      imports: [BusquedaComponent],
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);

    const fixture = TestBed.createComponent(BusquedaComponent);
    fixture.detectChanges();
    await tick();
    httpMock.expectOne('http://localhost:3000/api/doctors').flush({
      data: [
        {
          id: 'doc-1',
          name: 'Dra. Elena Ruiz',
          specialty: 'Cardiología',
          location: 'CDMX',
          price: 800,
        },
      ],
    });
    await tick();

    const openP = fixture.componentInstance.open(fixture.componentInstance.doctors()[0]);
    await tick();
    httpMock.expectOne('http://localhost:3000/api/doctors/doc-1').flush({
      data: {
        id: 'doc-1',
        name: 'Dra. Elena Ruiz',
        specialty: 'Cardiología',
        location: 'CDMX',
        price: 800,
        durationMin: 30,
        schedule: [],
        promotions: [],
      },
    });
    await tick();
    httpMock
      .expectOne((req) => req.url === 'http://localhost:3000/api/doctors/doc-1/availability')
      .flush({ data: { slots: ['2026-11-25T10:00:00-06:00'] } });
    await openP;
    fixture.detectChanges();

    fixture.componentInstance.selectSlot('2026-11-25T10:00:00-06:00');
    fixture.detectChanges();

    httpMock.expectNone('http://localhost:3000/api/appointments');
    expect(fixture.nativeElement.textContent).toContain('Paso 3 · Confirmar tu cita');

    const bookP = fixture.componentInstance.confirmBooking();
    await tick();
    const postReq = httpMock.expectOne('http://localhost:3000/api/appointments');
    expect(postReq.request.headers.get('Idempotency-Key')).toBeTruthy();
    postReq.flush({ data: { id: 'cita-1' } });
    await tick();
    httpMock
      .expectOne((req) => req.url === 'http://localhost:3000/api/doctors/doc-1/availability')
      .flush({ data: { slots: [] } });
    await bookP;
    fixture.detectChanges();

    expect(fixture.componentInstance.bookingSuccess()).toBe(true);
  });
});
