import { Component, inject, input, signal } from '@angular/core';
import { ApiService, MedicalDocument, MedicalRecord, errorMessage, formatDateTime } from './api.service';

/** Expediente en modo lectura: lo usan el paciente (historial) y el doctor autorizado. */
@Component({
  selector: 'midoc-expediente-vista',
  standalone: true,
  template: `
    @if (record(); as r) {
      @if (showClinicalData()) {
        <dl class="data">
          <dt>Paciente</dt><dd>{{ r.patient.name || r.patient.email }}</dd>
          <dt>Fecha de nacimiento</dt><dd>{{ r.birthDate || '—' }}</dd>
          <dt>Sexo</dt><dd>{{ r.sex || '—' }}</dd>
          <dt>Tipo de sangre</dt><dd>{{ r.bloodType || '—' }}</dd>
          <dt>Alergias</dt><dd>{{ r.allergies.join(', ') || 'Ninguna registrada' }}</dd>
          <dt>Padecimientos crónicos</dt><dd>{{ r.chronicConditions.join(', ') || 'Ninguno registrado' }}</dd>
          <dt>Medicamentos actuales</dt><dd>{{ r.medications.join(', ') || 'Ninguno registrado' }}</dd>
          <dt>Antecedentes y notas</dt><dd>{{ r.notes || '—' }}</dd>
        </dl>
      }
      <h3>Estudios y documentos</h3>
      <ul class="compact">
        @for (document of documents(); track document.id) {
          <li><a [href]="document.downloadUrl" target="_blank" rel="noopener">{{ document.name }}</a>
            <span class="muted"> · {{ formatSize(document.size) }}</span></li>
        } @empty { <li>No hay documentos clínicos adjuntos.</li> }
      </ul>
      <h3>Historial de consultas</h3>
      <ul class="history">
        @for (c of r.consultations; track c.appointmentId) {
          <li class="card">
            <strong>{{ formatDateTime(c.dateTime) }}</strong> · {{ c.doctorName }} ({{ c.specialty }})
            <p><b>Diagnóstico:</b> {{ c.diagnosis }}</p>
            <p><b>Tratamiento:</b> {{ c.treatment }}</p>
            @if (c.notes) { <p><b>Notas:</b> {{ c.notes }}</p> }
            @if (c.prescriptionId) {
              <button type="button" class="secondary" [disabled]="printing() === c.prescriptionId" (click)="printPrescription(c.prescriptionId)">
                {{ printing() === c.prescriptionId ? 'Preparando…' : 'Descargar o imprimir receta' }}
              </button>
            }
          </li>
        } @empty { <li>Todavía no hay consultas registradas.</li> }
      </ul>
      @if (prescriptionMessage()) { <p role="status" class="notice">{{ prescriptionMessage() }}</p> }
    }
  `
})
export class ExpedienteVistaComponent {
  private readonly api = inject(ApiService);
  readonly record = input.required<MedicalRecord | null>();
  readonly showClinicalData = input(true);
  readonly documents = input<MedicalDocument[]>([]);
  readonly formatDateTime = formatDateTime;
  readonly printing = signal<string | null>(null);
  readonly prescriptionMessage = signal('');

  formatSize(bytes: number): string {
    return bytes < 1_000_000 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1_000_000).toFixed(1)} MB`;
  }

  async printPrescription(id: string): Promise<void> {
    const printWindow = globalThis.open('', '_blank');
    if (!printWindow) {
      this.prescriptionMessage.set('Permite las ventanas emergentes para abrir la receta.');
      return;
    }
    this.printing.set(id);
    this.prescriptionMessage.set('');
    try {
      const prescription = await this.api.get<{
        diagnosis: string; treatment: string; dateTime: string; doctorName: string; specialty: string;
      }>(`/api/prescriptions/${id}`);
      const doc = printWindow.document;
      doc.open();
      doc.write('<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Receta MiDoc</title><style>body{font:16px/1.6 Arial,sans-serif;max-width:760px;margin:3rem auto;padding:0 2rem;color:#17352b}header{border-bottom:2px solid #246b59;padding-bottom:1rem}h1{font-size:2rem;color:#246b59}h2{margin-top:2rem;font-size:1rem;color:#476358}p{white-space:pre-wrap}.note{margin-top:3rem;color:#60756a;font-size:.85rem}@media print{body{margin:1cm auto}}</style></head><body></body></html>');
      doc.close();
      const header = doc.createElement('header');
      const title = doc.createElement('h1'); title.textContent = 'MiDoc · Receta médica'; header.append(title);
      const body = doc.createElement('main');
      const add = (label: string, value: string): void => {
        const heading = doc.createElement('h2'); heading.textContent = label; body.append(heading);
        const paragraph = doc.createElement('p'); paragraph.textContent = value; body.append(paragraph);
      };
      add('Profesional', `${prescription.doctorName} · ${prescription.specialty}`);
      add('Fecha de consulta', this.formatDateTime(prescription.dateTime));
      add('Diagnóstico', prescription.diagnosis);
      add('Tratamiento e indicaciones', prescription.treatment);
      const footer = doc.createElement('p'); footer.className = 'note';
      footer.textContent = 'Documento generado desde el expediente de MiDoc. Para fines de demostración.';
      body.append(footer);
      doc.body.replaceChildren(header, body);
      printWindow.focus();
      globalThis.setTimeout(() => printWindow.print(), 250);
    } catch (error) {
      printWindow.close();
      this.prescriptionMessage.set(errorMessage(error));
    } finally {
      this.printing.set(null);
    }
  }
}
