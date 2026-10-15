import { Component, input } from '@angular/core';
import { MedicalRecord, formatDateTime } from './api.service';

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
      <h3>Historial de consultas</h3>
      <ul class="history">
        @for (c of r.consultations; track c.appointmentId) {
          <li class="card">
            <strong>{{ formatDateTime(c.dateTime) }}</strong> · {{ c.doctorName }} ({{ c.specialty }})
            <p><b>Diagnóstico:</b> {{ c.diagnosis }}</p>
            <p><b>Tratamiento:</b> {{ c.treatment }}</p>
            @if (c.notes) { <p><b>Notas:</b> {{ c.notes }}</p> }
          </li>
        } @empty { <li>Todavía no hay consultas registradas.</li> }
      </ul>
    }
  `
})
export class ExpedienteVistaComponent {
  readonly record = input.required<MedicalRecord | null>();
  readonly showClinicalData = input(true);
  readonly formatDateTime = formatDateTime;
}
