import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  API_CONFIG_ERROR,
  API_URL,
  ApiService,
  PAYMENT_MODE,
  loadConfig,
  setApiConfigForTest,
} from './api.service';

describe('ApiService & loadConfig', () => {
  let api: ApiService;
  let httpMock: HttpTestingController;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    setApiConfigForTest('http://localhost:3000', 'test', '');
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  });

  afterEach(() => {
    httpMock.verify();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('loadConfig lee apiUrl y paymentMode desde config.json cuando forceFetch es true', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ apiUrl: 'https://api.midoc.example/', paymentMode: 'live' }), {
        status: 200,
      }),
    );

    await loadConfig({ forceFetch: true });

    expect(fetchSpy).toHaveBeenCalledWith('config.json', { cache: 'no-store' });
    expect(API_URL).toBe('https://api.midoc.example');
    expect(PAYMENT_MODE).toBe('live');
    expect(API_CONFIG_ERROR).toBe('');
  });

  it('cierra sesión y redirige a /acceso?reason=expired ante un error 401 con sesión activa', async () => {
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-1',
        user: { id: 'u1', email: 'ana@midoc.mx', role: 'PACIENTE', name: 'Ana' },
      }),
    );
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    const navSpy = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    const reqPromise = api.get('/api/records');
    const req = httpMock.expectOne('http://localhost:3000/api/records');
    req.flush({ error: 'Token expirado' }, { status: 401, statusText: 'Unauthorized' });

    await expect(reqPromise).rejects.toThrow('Token expirado');
    expect(api.user()).toBeNull();
    expect(navSpy).toHaveBeenCalledWith(['/acceso'], { queryParams: { reason: 'expired' } });
  });

  it('mantiene la sesión cuando PUT /api/me responde 400 por contraseña actual incorrecta', async () => {
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-doc',
        user: { id: 'd1', email: 'doc@midoc.mx', role: 'DOCTOR', name: 'Dr. Sol', doctorId: 'doc-1' },
      }),
    );
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    const navSpy = vi.spyOn(router, 'navigate');

    const updatePromise = api.updateMe({ currentPassword: 'wrong', newPassword: 'NewPassword1' });
    const req = httpMock.expectOne('http://localhost:3000/api/me');
    expect(req.request.method).toBe('PUT');
    req.flush({ error: 'La contraseña actual es incorrecta' }, { status: 400, statusText: 'Bad Request' });

    await expect(updatePromise).rejects.toThrow('La contraseña actual es incorrecta');
    expect(api.user()?.id).toBe('d1');
    expect(navSpy).not.toHaveBeenCalled();
  });

  it('consulta los nuevos endpoints M2: refreshSession, checkout/confirm/subscriptions, access-log y prescription', async () => {
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-1',
        user: { id: 'u1', email: 'doc@midoc.mx', role: 'DOCTOR', doctorId: 'doc-1' },
      }),
    );
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);

    const refreshP = api.refreshSession();
    httpMock.expectOne('http://localhost:3000/api/auth/refresh').flush({
      token: 'jwt-2',
      user: { id: 'u1', email: 'doc@midoc.mx', role: 'DOCTOR', name: 'Dr. Sol', doctorId: 'doc-1' },
    });
    await refreshP;
    expect(api.user()?.name).toBe('Dr. Sol');

    const checkoutP = api.createSubscriptionCheckout({ successUrl: 'https://s', cancelUrl: 'https://c' }, 'idem-1');
    const checkoutReq = httpMock.expectOne('http://localhost:3000/api/subscriptions/checkout');
    expect(checkoutReq.request.headers.get('Idempotency-Key')).toBe('idem-1');
    checkoutReq.flush({
      data: { sessionId: 'cs_1', checkoutUrl: 'https://checkout.stripe.com/pay/cs_1', mode: 'test', amountUsd: 20 },
    });
    const checkout = await checkoutP;
    expect(checkout.sessionId).toBe('cs_1');

    const confirmP = api.confirmSubscription('cs_1');
    httpMock.expectOne('http://localhost:3000/api/subscriptions/confirm').flush({
      data: { subscription: { status: 'ACTIVA', active: true, amount: 20 }, payment: { status: 'ACTIVA' } },
    });
    await confirmP;

    const subsP = api.getSubscriptions();
    httpMock.expectOne('http://localhost:3000/api/subscriptions').flush({
      data: { subscription: null, paymentMode: 'live', history: [] },
    });
    await subsP;
    expect(api.paymentMode()).toBe('live');

    const logP = api.getRecordAccessLog();
    httpMock.expectOne('http://localhost:3000/api/records/access-log').flush({ data: [] });
    expect(await logP).toEqual([]);

    const rxP = api.getPrescription('rx-1');
    httpMock.expectOne('http://localhost:3000/api/prescriptions/rx-1').flush({
      data: {
        id: 'rx-1',
        patientId: 'p1',
        doctorId: 'doc-1',
        diagnosis: 'dx',
        treatment: 'tx',
        dateTime: '2026-11-18T10:00:00Z',
        doctorName: 'Dr. Sol',
        specialty: 'General',
        downloadUrl: 'https://s3/rx.pdf',
        hasPdf: true,
      },
    });
    const rx = await rxP;
    expect(rx.downloadUrl).toBe('https://s3/rx.pdf');
  });
});
