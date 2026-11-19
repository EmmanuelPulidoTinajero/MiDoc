import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setApiConfigForTest } from './api.service';
import { ExpedienteComponent } from './expediente.component';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('ExpedienteComponent', () => {
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
    setApiConfigForTest('http://localhost:3000', 'test', '');
    localStorage.setItem(
      'midoc.session',
      JSON.stringify({
        token: 'jwt-p',
        user: { id: 'p1', email: 'ana@midoc.mx', role: 'PACIENTE', name: 'Ana' },
      }),
    );
    TestBed.configureTestingModule({
      imports: [ExpedienteComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('no duplica documentos, carga bitácora de accesos y confirma eliminación/revocación con DsModal', async () => {
    const fixture = TestBed.createComponent(ExpedienteComponent);
    fixture.detectChanges();
    await tick();

    httpMock.expectOne('http://localhost:3000/api/records').flush({
      data: {
        patient_id: 'p1',
        allergies: ['Polen'],
        notes: '',
        chronicConditions: [],
        medications: [],
        patient: { id: 'p1', name: 'Ana', email: 'ana@midoc.mx' },
        consultations: [],
      },
    });
    httpMock.expectOne('http://localhost:3000/api/consents').flush({
      data: [
        {
          doctorId: 'd1',
          doctorName: 'Dr. Sol',
          specialty: 'Medicina general',
          granted: true,
          updatedAt: '2026-11-18T10:00:00Z',
        },
      ],
    });
    httpMock.expectOne('http://localhost:3000/api/doctors').flush({ data: [] });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/records/documents').flush({
      data: [
        {
          id: 'doc-file-1',
          name: 'laboratorio-bh.pdf',
          contentType: 'application/pdf',
          size: 2048,
          lastModified: '2026-11-18T10:00:00Z',
          downloadUrl: 'https://s3/laboratorio-bh.pdf',
        },
      ],
    });
    httpMock.expectOne('http://localhost:3000/api/records/access-log').flush({
      data: [
        {
          id: 'log-1',
          actorId: 'u-d1',
          actorName: 'Dr. Sol',
          actorRole: 'DOCTOR',
          specialty: 'Medicina general',
          event: 'VER_EXPEDIENTE',
          accessedAt: '2026-11-18T11:00:00Z',
        },
      ],
    });
    await tick();
    fixture.detectChanges();

    const docLinks = fixture.nativeElement.querySelectorAll('a[href="https://s3/laboratorio-bh.pdf"]');
    expect(docLinks.length).toBe(1);
    expect(fixture.nativeElement.textContent).toContain('Quién vio mi expediente');
    expect(fixture.nativeElement.textContent).toContain('Lectura de expediente');

    const confirmSpy = vi.spyOn(globalThis, 'confirm');
    fixture.componentInstance.requestDeleteDocument(fixture.componentInstance.documents()[0]);
    fixture.detectChanges();
    const delP = fixture.componentInstance.confirmDeleteDocument();
    await tick();
    httpMock.expectOne('http://localhost:3000/api/records/documents/doc-file-1').flush({ data: { deleted: true } });
    await delP;
    expect(fixture.componentInstance.documents().length).toBe(0);
    expect(confirmSpy).not.toHaveBeenCalled();

    const badFile = new File([new Uint8Array(10)], 'estudio.exe', { type: 'application/octet-stream' });
    await fixture.componentInstance.uploadDocument({ target: { files: [badFile], value: '' } } as unknown as Event);
    expect(fixture.componentInstance.documentsMessage()).toContain('Formato no compatible');
    expect(fixture.componentInstance.consentMessage()).toBe('');

    fixture.componentInstance.requestRevokeConsent(fixture.componentInstance.consents()[0]);
    fixture.detectChanges();
    const revokeP = fixture.componentInstance.confirmRevokeConsent();
    await tick();
    httpMock.expectOne('http://localhost:3000/api/consents').flush({ data: { granted: false } });
    await tick();
    httpMock.expectOne('http://localhost:3000/api/consents').flush({ data: [] });
    await revokeP;
    expect(fixture.componentInstance.consentMessage()).toContain('Acceso revocado');
  });
});
