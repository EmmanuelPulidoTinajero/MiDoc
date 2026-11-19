import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setApiConfigForTest } from './api.service';
import { PanelDoctorComponent } from './panel-doctor.component';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('PanelDoctorComponent (Stripe real, perfil, inventario, promociones)', () => {
  let httpMock: HttpTestingController;
  let queryParams$: BehaviorSubject<ReturnType<typeof convertToParamMap>>;
  let router: Router;

  const baseMe = {
    id: 'u-d1',
    email: 'doc@midoc.mx',
    role: 'DOCTOR',
    name: 'Dr. Sol',
    phone: '3312345678',
    doctorId: 'doc-1',
    doctor: {
      id: 'doc-1',
      name: 'Dr. Sol',
      specialty: 'Medicina general',
      location: 'Av. Reforma 100',
      city: 'CDMX',
      price: 600,
      durationMin: 30,
      schedule: [],
    },
    subscription: { status: 'ACTIVA', amount: 20, start: '2026-11-01', end: '2026-12-01', active: true },
  };

  async function flushFullLoad(): Promise<void> {
    await tick();
    httpMock.expectOne('http://localhost:3000/api/me').flush({ data: baseMe });
    httpMock.expectOne('http://localhost:3000/api/subscriptions').flush({
      data: {
        subscription: baseMe.subscription,
        paymentMode: 'test',
        history: [
          {
            id: 'sub-1',
            status: 'ACTIVA',
            amount: 20,
            start: '2026-11-01',
            end: '2026-12-01',
            cardBrand: 'visa',
            cardLast4: '4242',
            paymentRef: 'cs_test_hist',
            paymentMode: 'test',
            active: true,
          },
        ],
      },
    });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/doctor/patients').flush({ data: [] });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/doctor/inventory').flush({
      data: [{ id: 'inv-1', name: 'Guantes', quantity: 5, unit: 'cajas' }],
    });
    httpMock.expectOne('http://localhost:3000/api/doctor/promotions').flush({
      data: [
        {
          id: 'promo-1',
          title: 'Buen Fin',
          description: 'Descuento',
          discountPercent: 15,
          start: '2026-11-18',
          end: '2026-11-30',
          active: true,
        },
      ],
    });
    await tick();
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
    setApiConfigForTest('http://localhost:3000', 'test', '');
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-doc',
        user: { id: 'u-d1', email: 'doc@midoc.mx', role: 'DOCTOR', name: 'Dr. Sol', doctorId: 'doc-1' },
      }),
    );
    queryParams$ = new BehaviorSubject(convertToParamMap({}));
    TestBed.configureTestingModule({
      imports: [PanelDoctorComponent],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { queryParamMap: queryParams$.asObservable() } },
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  });

  afterEach(() => {
    httpMock.verify();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('no contiene formularios de tarjeta ni texto de simulación y lanza Stripe Checkout real', async () => {
    const fixture = TestBed.createComponent(PanelDoctorComponent);
    fixture.detectChanges();
    await flushFullLoad();
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent as string;
    expect(text).not.toContain('simulación');
    expect(text).not.toContain('4242 4242');
    expect(text).toContain('Modo prueba (Stripe Sandbox)');
    expect(text).toContain('cs_test_hist');

    const redirectSpy = vi.spyOn(fixture.componentInstance, 'navigateExternal').mockImplementation(() => undefined);
    const checkoutP = fixture.componentInstance.startStripeCheckout();
    await tick();
    const req = httpMock.expectOne('http://localhost:3000/api/subscriptions/checkout');
    expect(req.request.headers.get('Idempotency-Key')).toBeTruthy();
    req.flush({
      data: {
        sessionId: 'cs_new',
        checkoutUrl: 'https://checkout.stripe.com/c/pay/cs_new',
        mode: 'test',
        amountUsd: 20,
      },
    });
    await checkoutP;
    expect(redirectSpy).toHaveBeenCalledWith('https://checkout.stripe.com/c/pay/cs_new');
  });

  it('confirma sesión Stripe al regresar con stripe_status=success&session_id=... y maneja cancel', async () => {
    const navSpy = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    const fixture = TestBed.createComponent(PanelDoctorComponent);
    fixture.detectChanges();
    await flushFullLoad();

    queryParams$.next(convertToParamMap({ stripe_status: 'success', session_id: 'cs_ok_123' }));
    await tick();
    const confirmReq = httpMock.expectOne('http://localhost:3000/api/subscriptions/confirm');
    expect(confirmReq.request.body).toEqual({ sessionId: 'cs_ok_123' });
    confirmReq.flush({
      data: {
        subscription: baseMe.subscription,
        payment: { cardBrand: 'mastercard', cardLast4: '5555' },
      },
    });
    await flushFullLoad();

    expect(fixture.componentInstance.subscriptionMessage()).toContain('Suscripción confirmada');
    expect(navSpy).toHaveBeenCalledWith(['/panel/suscripcion'], { replaceUrl: true });

    queryParams$.next(convertToParamMap({ stripe_status: 'cancel' }));
    expect(fixture.componentInstance.subscriptionTone()).toBe('warning');
    expect(fixture.componentInstance.subscriptionMessage()).toContain('cancelado en Stripe');
  });

  it('guarda perfil con PUT /api/me y edita promociones creando primero y retirando después', async () => {
    const fixture = TestBed.createComponent(PanelDoctorComponent);
    fixture.detectChanges();
    await flushFullLoad();

    const saveProfileP = fixture.componentInstance.saveProfile();
    await tick();
    const putMe = httpMock.expectOne('http://localhost:3000/api/me');
    expect(putMe.request.method).toBe('PUT');
    putMe.flush({ data: baseMe });
    await saveProfileP;
    expect(fixture.componentInstance.profileTone()).toBe('success');

    fixture.componentInstance.startEditPromotion(fixture.componentInstance.promotions()[0]);
    fixture.componentInstance.editPromotionForm.title = 'Navidad Salud';
    const editPromoP = fixture.componentInstance.saveEditPromotion();
    await tick();
    const postPromo = httpMock.expectOne('http://localhost:3000/api/doctor/promotions');
    expect(postPromo.request.method).toBe('POST');
    postPromo.flush({ data: { id: 'promo-2' } });
    await tick();
    const delOld = httpMock.expectOne('http://localhost:3000/api/doctor/promotions/promo-1');
    expect(delOld.request.method).toBe('DELETE');
    delOld.flush({ data: { deleted: true } });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/doctor/inventory').flush({ data: [] });
    httpMock.expectOne('http://localhost:3000/api/doctor/promotions').flush({ data: [] });
    await editPromoP;
    expect(fixture.componentInstance.promotionTone()).toBe('success');
  });

  it('distingue suscripción PENDIENTE de INACTIVA mostrando badge Pendiente y aviso de pago pendiente', async () => {
    const fixture = TestBed.createComponent(PanelDoctorComponent);
    fixture.detectChanges();
    await tick();

    const pendingSub = {
      status: 'PENDIENTE',
      amount: 20,
      start: '2026-11-18',
      end: '2026-11-18',
      active: false,
    };
    httpMock.expectOne('http://localhost:3000/api/me').flush({
      data: { ...baseMe, subscription: pendingSub },
    });
    httpMock.expectOne('http://localhost:3000/api/subscriptions').flush({
      data: {
        subscription: pendingSub,
        paymentMode: 'test',
        history: [],
      },
    });
    await tick();
    fixture.detectChanges();

    expect(fixture.componentInstance.subscriptionStatusKey()).toBe('PENDIENTE');
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Pendiente');
    expect(text).toContain('Pago pendiente de confirmación');
    expect(text).not.toContain('Suscripción vencida');
  });
});
