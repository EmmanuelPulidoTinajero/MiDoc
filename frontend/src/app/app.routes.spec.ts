import { LocationStrategy, HashLocationStrategy } from '@angular/common';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter, withHashLocation } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { routes } from './app.routes';
import { ApiService, setApiConfigForTest } from './api.service';

describe('app.routes y auth.guards (HashLocationStrategy)', () => {
  let router: Router;

  function setupSession(role: 'PACIENTE' | 'DOCTOR' | null): void {
    localStorage.clear();
    setApiConfigForTest('http://localhost:3000', 'test', '');
    if (role) {
      localStorage.setItem(
        'midoc.session',
        JSON.stringify({
          token: 'jwt-test',
          user: { id: 'u1', email: `${role.toLowerCase()}@midoc.mx`, role, name: 'Usuario Prueba' },
        }),
      );
    }
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideRouter(routes, withHashLocation()), provideHttpClient()],
    });
    router = TestBed.inject(Router);
  }

  beforeEach(() => {
    localStorage.clear();
  });

  it('usa HashLocationStrategy para compatibilidad con hosting estático S3', () => {
    setupSession(null);
    const strategy = TestBed.inject(LocationStrategy);
    expect(strategy).toBeInstanceOf(HashLocationStrategy);
  });

  it('redirige visitantes sin sesión desde /citas y /expediente hacia /acceso con returnUrl', async () => {
    setupSession(null);
    await router.navigateByUrl('/citas');
    expect(router.url).toBe('/acceso?returnUrl=%2Fcitas');

    await router.navigateByUrl('/expediente');
    expect(router.url).toBe('/acceso?returnUrl=%2Fexpediente');
  });

  it('protege /expediente sólo para pacientes y /panel/* sólo para doctores/clínicas', async () => {
    setupSession('DOCTOR');
    await router.navigateByUrl('/expediente');
    expect(router.url).toBe('/panel');

    await router.navigateByUrl('/panel/suscripcion?stripe_status=success&session_id=cs_test_1');
    expect(router.url).toBe('/panel/suscripcion?stripe_status=success&session_id=cs_test_1');

    setupSession('PACIENTE');
    await router.navigateByUrl('/panel/suscripcion');
    expect(router.url).toBe('/buscar');

    await router.navigateByUrl('/acceso');
    expect(router.url).toBe('/buscar');
  });

  it('mantiene instancia de ApiService coherente con la sesión', () => {
    setupSession('DOCTOR');
    const api = TestBed.inject(ApiService);
    expect(api.isDoctor()).toBe(true);
    expect(api.isPatient()).toBe(false);
  });
});
