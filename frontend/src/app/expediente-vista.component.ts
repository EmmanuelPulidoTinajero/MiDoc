import { Component, inject, input, signal } from '@angular/core';
import {
  ApiService,
  MedicalDocument,
  MedicalRecord,
  errorMessage,
  formatDateTime,
} from './api.service';
import {
  DsAlertBannerComponent,
  DsButtonComponent,
  DsCardComponent,
  DsEmptyStateComponent,
} from './ds';

/** Expediente en modo lectura: lo usan el paciente (historial) y el doctor autorizado. */
@Component({
  selector: 'midoc-expediente-vista',
  standalone: true,
  imports: [DsAlertBannerComponent, DsButtonComponent, DsCardComponent, DsEmptyStateComponent],
  template: `
    @if (record(); as r) {
      <div class="stack">
        @if (showClinicalData()) {
          <dl class="data">
            <dt>Paciente</dt>
            <dd>{{ r.patient.name || r.patient.email }}</dd>
            <dt>Fecha de nacimiento</dt>
            <dd>{{ r.birthDate || '—' }}</dd>
            <dt>Sexo</dt>
            <dd>{{ r.sex || '—' }}</dd>
            <dt>Tipo de sangre</dt>
            <dd>{{ r.bloodType || '—' }}</dd>
            <dt>Alergias</dt>
            <dd>{{ r.allergies.join(', ') || 'Ninguna registrada' }}</dd>
            <dt>Padecimientos crónicos</dt>
            <dd>{{ r.chronicConditions.join(', ') || 'Ninguno registrado' }}</dd>
            <dt>Medicamentos actuales</dt>
            <dd>{{ r.medications.join(', ') || 'Ninguno registrado' }}</dd>
            <dt>Antecedentes y notas</dt>
            <dd>{{ r.notes || '—' }}</dd>
          </dl>
        }

        @if (showDocuments()) {
          <div>
            <h3>Estudios y documentos</h3>
            @if (documents().length) {
              <ul class="compact">
                @for (document of documents(); track document.id) {
                  <li>
                    <a [href]="document.downloadUrl" target="_blank" rel="noopener">{{ document.name }}</a>
                    <span class="muted"> · {{ formatSize(document.size) }}</span>
                  </li>
                }
              </ul>
            } @else {
              <p class="muted">No hay documentos clínicos adjuntos.</p>
            }
          </div>
        }

        <div>
          <h3>Historial de consultas y recetas</h3>
          @if (r.consultations.length) {
            <ul class="history">
              @for (c of r.consultations; track c.appointmentId) {
                <li>
                  <ds-card tone="muted" padding="md">
                    <div class="stack-sm">
                      <div class="row">
                        <strong>{{ formatDateTime(c.dateTime) }}</strong>
                        <span class="muted">{{ c.doctorName }} · {{ c.specialty }}</span>
                      </div>
                      <p style="margin: 0;"><strong>Diagnóstico:</strong> {{ c.diagnosis }}</p>
                      <p style="margin: 0;"><strong>Tratamiento:</strong> {{ c.treatment }}</p>
                      @if (c.notes) {
                        <p style="margin: 0;"><strong>Notas:</strong> {{ c.notes }}</p>
                      }
                      @if (c.prescriptionId) {
                        <div class="row-start" style="margin-top: var(--space-1);">
                          <ds-button
                            variant="secondary"
                            size="sm"
                            [loading]="downloading() === c.prescriptionId"
                            (pressed)="downloadPdf(c.prescriptionId)"
                          >
                            {{ downloading() === c.prescriptionId ? 'Obteniendo PDF…' : 'Descargar PDF' }}
                          </ds-button>
                          <ds-button
                            variant="ghost"
                            size="sm"
                            [loading]="printing() === c.prescriptionId"
                            (pressed)="printPrescription(c.prescriptionId)"
                          >
                            {{ printing() === c.prescriptionId ? 'Preparando…' : 'Imprimir receta' }}
                          </ds-button>
                        </div>
                      }
                    </div>
                  </ds-card>
                </li>
              }
            </ul>
          } @else {
            <ds-empty-state
              icon="file"
              title="Sin consultas registradas"
              description="Cuando concluyas una consulta médica, el resumen y la receta aparecerán aquí."
            />
          }
        </div>

        @if (prescriptionMessage()) {
          <ds-alert-banner
            [tone]="prescriptionTone()"
            [message]="prescriptionMessage()"
            [dismissible]="true"
            (dismissed)="prescriptionMessage.set('')"
          />
        }
      </div>
    }
  `,
})
export class ExpedienteVistaComponent {
  private readonly api = inject(ApiService);
  readonly record = input.required<MedicalRecord | null>();
  readonly showClinicalData = input(true);
  readonly showDocuments = input(true);
  readonly documents = input<MedicalDocument[]>([]);
  readonly formatDateTime = formatDateTime;
  readonly printing = signal<string | null>(null);
  readonly downloading = signal<string | null>(null);
  readonly prescriptionMessage = signal('');
  readonly prescriptionTone = signal<'info' | 'warning' | 'danger'>('info');

  formatSize(bytes: number): string {
    return bytes < 1_000_000 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1_000_000).toFixed(1)} MB`;
  }

  async downloadPdf(id: string): Promise<void> {
    this.downloading.set(id);
    this.prescriptionMessage.set('');
    try {
      const prescription = await this.api.getPrescription(id);
      if (prescription.downloadUrl) {
        globalThis.open(prescription.downloadUrl, '_blank', 'noopener');
      } else {
        this.prescriptionTone.set('info');
        this.prescriptionMessage.set(
          'El PDF se genera al almacenar recetas en S3; puedes usar «Imprimir receta» para obtener una copia inmediata.',
        );
      }
    } catch (error) {
      this.prescriptionTone.set('danger');
      this.prescriptionMessage.set(errorMessage(error));
    } finally {
      this.downloading.set(null);
    }
  }

  async printPrescription(id: string): Promise<void> {
    const printWindow = globalThis.open('', '_blank');
    if (!printWindow) {
      this.prescriptionTone.set('warning');
      this.prescriptionMessage.set('Permite las ventanas emergentes para abrir la versión imprimible de la receta.');
      return;
    }
    this.printing.set(id);
    this.prescriptionMessage.set('');
    try {
      const prescription = await this.api.getPrescription(id);
      const doc = printWindow.document;
      doc.documentElement.lang = 'es-MX';
      doc.title = `Receta MiDoc · ${prescription.id}`;

      const style = doc.createElement('style');
      style.textContent =
        'body{font-family:system-ui,sans-serif;line-height:1.6;max-width:46rem;margin:2.5rem auto;padding:0 1.5rem;color:CanvasText}header{border-bottom:2px solid currentColor;padding-bottom:.75rem;margin-bottom:1.5rem}h1{font-family:ui-serif,Georgia,serif;font-size:1.75rem;margin:0}h2{font-size:.95rem;text-transform:uppercase;letter-spacing:.05em;margin-top:1.5rem;margin-bottom:.25rem}p{white-space:pre-wrap;margin:0}.note{margin-top:2.5rem;font-size:.85rem;opacity:.8}@media print{body{margin:1cm auto}}';
      doc.head.replaceChildren(style);

      const header = doc.createElement('header');
      const title = doc.createElement('h1');
      title.textContent = 'MiDoc · Receta médica';
      const folio = doc.createElement('p');
      folio.textContent = `Folio: ${prescription.id}`;
      header.append(title, folio);

      const main = doc.createElement('main');
      const add = (label: string, value: string): void => {
        const heading = doc.createElement('h2');
        heading.textContent = label;
        const paragraph = doc.createElement('p');
        paragraph.textContent = value;
        main.append(heading, paragraph);
      };
      if (prescription.patientName) {
        add('Paciente', prescription.patientName);
      }
      add('Profesional', `${prescription.doctorName} · ${prescription.specialty}`);
      add('Fecha de consulta', this.formatDateTime(prescription.dateTime));
      add('Diagnóstico', prescription.diagnosis);
      add('Tratamiento e indicaciones', prescription.treatment);

      const footer = doc.createElement('p');
      footer.className = 'note';
      footer.textContent = 'Documento emitido electrónicamente desde MiDoc.';
      main.append(footer);

      doc.body.replaceChildren(header, main);
      printWindow.focus();
      globalThis.setTimeout(() => printWindow.print(), 250);
    } catch (error) {
      printWindow.close();
      this.prescriptionTone.set('danger');
      this.prescriptionMessage.set(errorMessage(error));
    } finally {
      this.printing.set(null);
    }
  }
}
