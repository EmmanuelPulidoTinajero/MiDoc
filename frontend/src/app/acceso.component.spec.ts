import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AccesoComponent } from './acceso.component';
import { setApiConfigForTest } from './api.service';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('AccesoComponent', () => {
  let httpMock: HttpTestingController;
  let router: Router;

  beforeEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
    setApiConfigForTest('http://localhost:3000', 'test', '');
    TestBed.configureTestingModule({
      imports: [AccesoComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('no muestra credenciales de demostración y limpia mensajes al cambiar entre Iniciar sesión y Crear cuenta', () => {
    const fixture = TestBed.createComponent(AccesoComponent);
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent as string;
    expect(text).not.toContain('Cuentas de demostración');
    expect(text).not.toContain('paciente@midoc.local');

    fixture.componentInstance.message.set('Error temporal');
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Error temporal');

    fixture.componentInstance.setMode('register');
    fixture.detectChanges();
    expect(fixture.componentInstance.message()).toBe('');
  });

  it('valida en línea correo inválido, contraseña débil y campos obligatorios de doctor', async () => {
    const fixture = TestBed.createComponent(AccesoComponent);
    fixture.detectChanges();

    fixture.componentInstance.email = 'correo-malo';
    fixture.componentInstance.password = '';
    await fixture.componentInstance.login();
    fixture.detectChanges();

    expect(fixture.componentInstance.errors().email).toBeTruthy();
    expect(fixture.componentInstance.errors().password).toBeTruthy();
    expect(fixture.nativeElement.querySelectorAll('[role="alert"]').length).toBeGreaterThanOrEqual(2);

    fixture.componentInstance.setMode('register');
    fixture.componentInstance.role = 'DOCTOR';
    fixture.componentInstance.name = 'A';
    fixture.componentInstance.email = 'doc@midoc.mx';
    fixture.componentInstance.password = '1234';
    await fixture.componentInstance.register();
    fixture.detectChanges();

    expect(fixture.componentInstance.errors().name).toBeTruthy();
    expect(fixture.componentInstance.errors().password).toBeTruthy();
    expect(fixture.componentInstance.errors().specialty).toBeTruthy();
    expect(fixture.componentInstance.errors().location).toBeTruthy();
  });

  it('redirige al panel profesional cuando un doctor inicia sesión exitosamente', async () => {
    const navSpy = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    const fixture = TestBed.createComponent(AccesoComponent);
    fixture.detectChanges();

    fixture.componentInstance.email = 'doc@midoc.mx';
    fixture.componentInstance.password = 'Password1';
    const loginPromise = fixture.componentInstance.login();
    await tick();

    httpMock.expectOne('http://localhost:3000/api/auth/login').flush({
      token: 'jwt-doc',
      user: { id: 'u2', email: 'doc@midoc.mx', role: 'DOCTOR' },
    });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/me').flush({
      data: { id: 'u2', email: 'doc@midoc.mx', role: 'DOCTOR', name: 'Dr. Sol', doctorId: 'd1' },
    });

    await loginPromise;
    expect(navSpy).toHaveBeenCalledWith(['/panel']);
  });
});
