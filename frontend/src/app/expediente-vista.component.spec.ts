import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MedicalDocument, MedicalRecord, setApiConfigForTest } from './api.service';
import { ExpedienteVistaComponent } from './expediente-vista.component';

@Component({
  standalone: true,
  imports: [ExpedienteVistaComponent],
  template: `
    <midoc-expediente-vista
      [record]="record()"
      [documents]="documents()"
      [showClinicalData]="true"
      [showDocuments]="showDocuments()"
    />
  `,
})
class VistaHostComponent {
  readonly showDocuments = signal(true);
  readonly documents = signal<MedicalDocument[]>([
    {
      id: 'd1',
      name: 'rx-torax.pdf',
      contentType: 'application/pdf',
      size: 1024,
      lastModified: '2026-11-18T10:00:00Z',
      downloadUrl: 'https://s3/rx-torax.pdf',
    },
  ]);
  readonly record = signal<MedicalRecord>({
    patient_id: 'p1',
    allergies: [],
    notes: '',
    chronicConditions: [],
    medications: [],
    patient: { id: 'p1', name: 'Ana', email: 'ana@midoc.mx' },
    consultations: [
      {
        prescriptionId: 'rx-1',
        appointmentId: 'a1',
        dateTime: '2026-11-18T10:00:00Z',
        doctorName: 'Dr. Sol',
        specialty: 'Medicina general',
        diagnosis: 'Resfriado',
        treatment: 'Hidratación',
      },
    ],
  });
}

describe('ExpedienteVistaComponent', () => {
  let httpMock: HttpTestingController;

  beforeEach(() => {
    setApiConfigForTest('http://localhost:3000', 'test', '');
    TestBed.configureTestingModule({
      imports: [VistaHostComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    vi.restoreAllMocks();
  });

  it('respeta showDocuments, abre downloadUrl del PDF y la impresión no contiene texto de demostración', async () => {
    const fixture = TestBed.createComponent(VistaHostComponent);
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('rx-torax.pdf');
    fixture.componentInstance.showDocuments.set(false);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('rx-torax.pdf');

    const openSpy = vi.spyOn(globalThis, 'open').mockReturnValue(null);
    const vista = fixture.debugElement.children[0].componentInstance as ExpedienteVistaComponent;

    const dlP = vista.downloadPdf('rx-1');
    httpMock.expectOne('http://localhost:3000/api/prescriptions/rx-1').flush({
      data: {
        id: 'rx-1',
        patientId: 'p1',
        doctorId: 'doc-1',
        diagnosis: 'Resfriado',
        treatment: 'Hidratación',
        dateTime: '2026-11-18T10:00:00Z',
        doctorName: 'Dr. Sol',
        specialty: 'Medicina general',
        downloadUrl: 'https://s3/receta-rx-1.pdf',
        hasPdf: true,
      },
    });
    await dlP;
    expect(openSpy).toHaveBeenCalledWith('https://s3/receta-rx-1.pdf', '_blank', 'noopener');

    const fakeDoc = document.implementation.createHTMLDocument('Receta');
    const fakeWin = {
      document: fakeDoc,
      focus: vi.fn(),
      print: vi.fn(),
      close: vi.fn(),
    } as unknown as Window;
    openSpy.mockReturnValue(fakeWin);

    const printP = vista.printPrescription('rx-1');
    httpMock.expectOne('http://localhost:3000/api/prescriptions/rx-1').flush({
      data: {
        id: 'rx-1',
        patientId: 'p1',
        doctorId: 'doc-1',
        diagnosis: 'Resfriado',
        treatment: 'Hidratación',
        dateTime: '2026-11-18T10:00:00Z',
        doctorName: 'Dr. Sol',
        specialty: 'Medicina general',
        patientName: 'Ana',
        downloadUrl: null,
        hasPdf: false,
      },
    });
    await printP;

    expect(fakeDoc.body.textContent).toContain('Folio: rx-1');
    expect(fakeDoc.body.textContent).toContain('Documento emitido electrónicamente desde MiDoc.');
    expect(fakeDoc.body.textContent).not.toContain('Para fines de demostración');
  });
});
